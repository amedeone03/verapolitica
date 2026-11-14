"""Regione, Provincia, Comune: the redazione writes the model's blocks on top of the official base."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Municipality, RawDocument, RawDocumentStatus, Region, Source, TerritorialOfficeMandate

ANNA = {"Authorization": "Bearer tok-anna-redattrice"}
BRUNO = {"Authorization": "Bearer tok-bruno-verificatore"}
CARLA = {"Authorization": "Bearer tok-carla-caporedattrice"}
MEMBERS = "Anna Redattrice=tok-anna-redattrice;Bruno Verificatore=tok-bruno-verificatore;Carla Caporedattrice=tok-carla-caporedattrice"
NOW = datetime(2026, 11, 6, 9, tzinfo=timezone.utc)
ISTAT = {"name": "ISTAT, popolazione residente al 1° gennaio 2026", "url": "https://demo.istat.it/app/?i=POS&l=it&a=2026"}


def _seed(factory) -> dict:
    with factory() as session:
        source = Source(key="istat", name="ISTAT", base_url="https://www.istat.it")
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id, retrieved_at=NOW, source_url="https://www.istat.it/comuni", content_type="text/csv",
            storage_key="test/comuni", raw_sha256="0" * 64, structured_records=[], normalized_text="x",
            process_status=RawDocumentStatus.PARSED, collector_version="t", parser_version="t",
        )
        session.add(document)
        session.flush()
        region = Region(istat_code="03", canonical_name="Lombardia", source_id=source.id, raw_document_id=document.id, source_url="https://www.istat.it/regioni")
        session.add(region)
        session.flush()
        milano = Municipality(istat_code="015146", region_id=region.id, canonical_name="Milano", province_abbreviation="MI", province_name="Milano", source_id=source.id, raw_document_id=document.id, source_url="https://www.istat.it/comuni")
        session.add(milano)
        session.commit()
        return {"region": region.id, "municipality": milano.id}


def _client(tmp_path, admins: str | None = None):
    url = f"sqlite:///{tmp_path / 'territori.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    ids = _seed(create_session_factory(engine))
    settings = Settings(
        database_url=url, raw_storage_path=tmp_path / "raw", admin_api_key="redazione-admin",
        redazione_members=MEMBERS, redazione_admins=admins,
    )
    return TestClient(create_app(settings)), ids, engine


@pytest.fixture
def console(tmp_path):
    client, ids, engine = _client(tmp_path)
    with client:
        yield client, ids
    engine.dispose()


def test_the_scheda_follows_the_writing_models_and_keeps_the_official_base(console):
    client, ids = console
    region = client.get(f"/redazione/api/territori/region/{ids['region']}", headers=ANNA).json()
    assert [block["key"] for block in region["definitions"]] == [
        "rapida", "utile", "indirizzo", "come_funziona", "presidente", "giunta", "consiglio", "promesse", "elezioni", "titolare",
    ]
    giunta = next(block for block in region["definitions"] if block["key"] == "giunta")
    assert [column["key"] for column in giunta["columns"]] == ["ruolo", "nome", "partito", "delega"]
    consiglio = next(block for block in region["definitions"] if block["key"] == "consiglio")
    assert consiglio["type"] == "rows" and [column["key"] for column in consiglio["columns"]] == ["gruppo", "consiglieri", "capogruppo", "sostiene_giunta"]
    assert region["base"]["name"] == "Lombardia" and region["base"]["municipality_count"] == 1
    assert region["base"]["provinces"] == [{"abbreviation": "MI", "name": "Milano", "municipalities": 1}]
    town = client.get(f"/redazione/api/territori/municipality/{ids['municipality']}", headers=ANNA).json()
    assert [block["title"] for block in town["definitions"]] == [
        "Scheda rapida", "Cosa conta", "Indirizzo politico", "Come funziona", "Il sindaco", "La giunta",
        "Consiglio e opposizione", "Promesse del mandato", "Elezioni (storico e prossime)", "Collega il sindaco",
    ]
    assert town["base"]["province"] == {"abbreviation": "MI", "name": "Milano"}
    province = client.get("/redazione/api/territori/province/mi", headers=ANNA).json()
    assert province["base"]["name"] == "Milano" and province["base"]["key"] == "MI"
    assert client.get("/redazione/api/territori/region/999", headers=ANNA).status_code == 404
    # The console finds territories by name.
    found = client.get("/redazione/api/territori?q=mil", headers=ANNA).json()
    assert {row["kind"] for row in found} == {"province", "municipality"}
    # Capoluoghi (Milano, Verona, …) appear on the Comuni tab without a query.
    empty = client.get("/redazione/api/territori", headers=ANNA).json()
    assert any(row["kind"] == "municipality" and row["name"] == "Milano" for row in empty)
    assert any(row["kind"] == "municipio" and row["key"] == "roma-1" for row in empty)
    exact = [row for row in client.get("/redazione/api/territori?q=Milano", headers=ANNA).json() if row["kind"] == "municipality"]
    assert exact and exact[0]["name"] == "Milano"


def test_a_block_goes_through_the_second_person_and_any_published_block_can_change(console):
    client, ids = console
    path = f"/redazione/api/territori/municipality/{ids['municipality']}/blocchi/sindaco"
    body = "Giuseppe Sala (lista civica, centrosinistra) è sindaco di Milano dal giugno 2016 ed è stato rieletto nell'ottobre 2021. In precedenza è stato commissario unico di Expo 2015 e direttore generale del Comune di Milano."
    saved = client.post(path, headers=ANNA, json={"body": body, "sources": [{"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco"}]})
    assert saved.status_code == 200, saved.text
    item = next(item for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "territory")
    assert item["title"] == "Comune di Milano — Il sindaco"
    assert item["territory"] == {"kind": "municipality", "key": str(ids["municipality"]), "title": "Comune di Milano"}
    # Not published yet: the citizen sees the base only.
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    assert next(block for block in public["blocks"] if block["key"] == "sindaco")["data"] is None
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    sindaco = next(block for block in public["blocks"] if block["key"] == "sindaco")
    assert sindaco["data"]["body"] == body and sindaco["written_by"] == "Anna Redattrice" and sindaco["published_by"] == "Bruno Verificatore"
    assert {"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco", "date": None} in public["sources"]
    # A published block can always be changed: the new version replaces it once approved.
    client.post(path, headers=BRUNO, json={"body": body.replace("giugno 2016", "1° luglio 2016"), "sources": [{"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco"}]})
    second = next(item for item in client.get("/redazione/api/coda", headers=ANNA).json() if item["kind"] == "territory")
    client.post(f"/redazione/api/coda/territory/{second['id']}/approva", headers=ANNA, json={})
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    assert "1° luglio 2016" in next(block for block in public["blocks"] if block["key"] == "sindaco")["data"]["body"]
    scheda = client.get(f"/redazione/api/territori/municipality/{ids['municipality']}", headers=ANNA).json()
    assert scheda["blocks"]["sindaco"]["published"]["created_by"] == "Bruno Verificatore"
    assert scheda["blocks"]["sindaco"]["pending"] == []


def test_the_rules_of_the_models_block_publication(console):
    client, ids = console
    base = f"/redazione/api/territori/region/{ids['region']}/blocchi"
    # Open brackets and a missing source are errors; a population needs its year.
    client.post(f"{base}/presidente", headers=ANNA, json={"body": "Attilio Fontana (Lega) è presidente dal [data]."})
    client.post(f"{base}/rapida", headers=ANNA, json={"fields": {"capoluogo": "Milano", "popolazione": "10.035.481"}, "sources": [ISTAT]})
    client.post(f"{base}/promesse", headers=ANNA, json={"rows": [{"promessa": "Nuova linea ferroviaria", "quando": "Programma 2023", "stato": "non_mantenuta", "aggiornamento": "", "fonte": ""}], "sources": [ISTAT]})
    queue = [item for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "territory"]
    codes = {item["title"].split(" — ")[1]: {finding["code"] for finding in item["findings"]} for item in queue}
    assert {"parentesi_aperte", "fonte_mancante"} <= codes["Il presidente"]
    assert "anno_mancante" in codes["Scheda rapida"]
    assert {"fonte_mancante", "motivo_mancante"} <= codes["Promesse del mandato"]
    assert all(item["blocked"] for item in queue)
    blocked = client.post(f"/redazione/api/coda/territory/{queue[0]['id']}/approva", headers=BRUNO, json={})
    assert blocked.status_code == 422
    # Unknown blocks and fields are refused or dropped.
    assert client.post(f"{base}/sindaco", headers=ANNA, json={"body": "x"}).status_code == 404
    client.post(f"{base}/rapida", headers=ANNA, json={"fields": {"capoluogo": "Milano", "tipo": "inventato", "colore": "verde"}, "sources": [ISTAT]})
    scheda = client.get(f"/redazione/api/territori/region/{ids['region']}", headers=ANNA).json()
    data = scheda["blocks"]["rapida"]["pending"][-1]["data"]
    assert data["tipo"] == "" and "colore" not in data
    # The writer's newer version replaces their own older pending one.
    assert len(scheda["blocks"]["rapida"]["pending"]) == 1


def test_an_admin_publishes_at_once(tmp_path):
    client, ids, engine = _client(tmp_path, admins="Carla Caporedattrice")
    with client:
        saved = client.post(
            f"/redazione/api/territori/province/MI/blocchi/presidente",
            headers=CARLA,
            json={"body": "Il presidente della Provincia di Milano è eletto da sindaci e consiglieri comunali. [nome, lista, in carica dal]", "sources": [ISTAT]},
        ).json()
        # Open brackets: saved, but not published even by an admin.
        assert saved["published"] is False
        saved = client.post(
            f"/redazione/api/territori/province/MI/blocchi/consiglio",
            headers=CARLA,
            json={"body": "Il consiglio provinciale è eletto da sindaci e consiglieri comunali dei comuni della provincia, con voto ponderato sulla popolazione.", "sources": [{"name": "Città metropolitana di Milano", "url": "https://www.cittametropolitana.mi.it/portale/consiglio"}]},
        ).json()
        assert saved["published"] is True
        public = client.get("/territories/province/MI").json()
        assert public["blocks"][2]["published_by"] == "Carla Caporedattrice"
        # Without an admin role, a writer's save waits.
        waiting = client.post("/redazione/api/territori/province/MI/blocchi/elezioni", headers=ANNA, json={"body": "Testo.", "sources": [ISTAT]}).json()
        assert waiting.get("published") is not True and waiting["status"] == "pending"
    engine.dispose()


def test_regions_overview_shows_the_coalition_the_redazione_published(tmp_path):
    client, ids, engine = _client(tmp_path, admins="Carla Caporedattrice")
    with client:
        empty = client.get("/territories/regions").json()
        assert empty["items"][0]["short"] == "LOM" and empty["items"][0]["coalition"] is None
        assert empty["counts"] == {
            "centrosinistra": 0,
            "centrodestra": 0,
            "indipendente_destra": 0,
            "indipendente_sinistra": 0,
            "autonomista": 0,
            "altro": 0,
            "da_compilare": 1,
        }
        client.post(
            f"/redazione/api/territori/region/{ids['region']}/blocchi/rapida",
            headers=CARLA,
            json={"fields": {"capoluogo": "Milano", "coalizione": "centrodestra", "prossime_elezioni": "Primavera 2028"}, "sources": [ISTAT]},
        )
        overview = client.get("/territories/regions").json()
        lombardia = overview["items"][0]
        assert lombardia["coalition"] == "centrodestra" and lombardia["coalition_label"] == "Centrodestra"
        assert lombardia["next_election"] == "Primavera 2028"
        assert overview["counts"]["centrodestra"] == 1 and overview["counts"]["da_compilare"] == 0
        # A value outside the list is not stored.
        client.post(f"/redazione/api/territori/region/{ids['region']}/blocchi/rapida", headers=CARLA, json={"fields": {"capoluogo": "Milano", "coalizione": "inventata"}, "sources": [ISTAT]})
        assert client.get("/territories/regions").json()["items"][0]["coalition"] is None
    engine.dispose()


def test_parliament_composition_counts_open_memberships_of_the_current_legislature(tmp_path):
    from datetime import date

    from sqlalchemy.orm import Session

    from backend.app.models import ParliamentaryGroup, Politician
    from backend.app.models.parliamentary_group_membership import ParliamentaryGroupMembership
    from backend.app.services import normalize_person_name

    client, _, engine = _client(tmp_path)
    with Session(engine) as session:
        source = session.query(Source).first()
        document = session.query(RawDocument).first()
        old = ParliamentaryGroup(canonical_name="Gruppo della XVIII", abbreviation="OLD", institution="Camera dei Deputati", legislature="XVIII")
        big = ParliamentaryGroup(canonical_name="Gruppo grande", abbreviation="GG", institution="Camera dei Deputati", legislature="XIX")
        small = ParliamentaryGroup(canonical_name="Gruppo piccolo", abbreviation="GP", institution="Camera dei Deputati", legislature="XIX")
        senate = ParliamentaryGroup(canonical_name="Gruppo del Senato", abbreviation="GS", institution="Senato della Repubblica", legislature="19")
        session.add_all([old, big, small, senate])
        session.flush()
        people = []
        for index in range(6):
            person = Politician(canonical_given_name="Persona", canonical_family_name=f"Numero{index}", normalized_name=normalize_person_name("Persona", f"Numero{index}"))
            session.add(person)
            people.append(person)
        session.flush()

        def member(person, group, key, end=None):
            session.add(ParliamentaryGroupMembership(
                politician_id=person.id, parliamentary_group_id=group.id, source_id=source.id, raw_document_id=document.id,
                identity_key=key, source_url="https://dati.camera.it/x", start_date=date(2022, 10, 13), end_date=end,
            ))

        member(people[0], big, "a")
        member(people[1], big, "b")
        member(people[2], big, "c")
        member(people[3], small, "d")
        member(people[4], small, "e", end=date(2024, 1, 1))  # left the group
        member(people[5], old, "f")  # previous legislature
        member(people[5], senate, "g")
        session.commit()
    with client:
        data = client.get("/parliament/composition").json()
    engine.dispose()
    camera = data["camera"]
    assert camera["legislature"] == 19 and camera["seats_by_law"] == 400
    assert [(group["abbreviation"], group["seats"]) for group in camera["groups"]] == [("GG", 3), ("GP", 1)]
    assert camera["counted"] == 4 and camera["majority"] == 3
    assert data["senato"]["groups"] == [{"id": data["senato"]["groups"][0]["id"], "name": "Gruppo del Senato", "abbreviation": "GS", "seats": 1}]


def _photo(colour=(30, 120, 80), size=(2400, 1600)) -> str:
    from base64 import b64encode
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + b64encode(buffer.getvalue()).decode()


def test_coat_of_arms_and_cover_photo_for_every_territory(console):
    client, ids = console
    from base64 import b64encode
    from io import BytesIO

    from PIL import Image

    bmp = BytesIO()
    Image.new("RGB", (64, 64), (10, 40, 90)).save(bmp, format="BMP")
    bmp_upload = client.post(
        "/redazione/api/immagini",
        headers=ANNA,
        json={"data": "data:image/bmp;base64," + b64encode(bmp.getvalue()).decode(), "purpose": "logo"},
    )
    assert bmp_upload.status_code == 200, bmp_upload.text
    slots = client.get(f"/redazione/api/territori/municipality/{ids['municipality']}/immagini", headers=ANNA).json()["slots"]
    assert [(slot["kind"], slot["label"], slot["photo"]) for slot in slots] == [("municipality", "Stemma", False), ("municipality_photo", "Foto", True)]
    assert client.get("/redazione/api/territori/province/xx/immagini", headers=ANNA).status_code == 404

    # The photo is compressed by the server for its use (a cover: longest side 1800px, WebP).
    image = client.post("/redazione/api/immagini", headers=ANNA, json={"data": _photo(), "purpose": "photo"}).json()
    assert (image["width"], image["height"]) == (1800, 1200) and image["saved_percent"] > 0
    assert client.get(image["url"]).headers["content-type"] == "image/webp"
    proposal = client.post("/redazione/api/simboli", headers=ANNA, json={
        "kind": "province_photo", "key": "MI", "image_id": image["id"], "credit": "Mario Rossi",
        "license": "cc-by-sa", "source_url": "https://commons.wikimedia.org/wiki/File:Milano.jpg",
    })
    assert proposal.status_code == 200, proposal.text
    pending = client.get("/redazione/api/territori/province/MI/immagini", headers=ANNA).json()["slots"][1]["pending"]
    assert len(pending) == 1
    assert client.get("/territories/province/MI").json()["images"]["photo"] is None
    # A second member approves; the author cannot.
    assert client.post(f"/redazione/api/coda/change/{proposal.json()['id']}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/change/{proposal.json()['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get("/territories/province/MI").json()["images"]
    assert public["photo"]["url"] == image["url"] and public["photo"]["credit"] == "Mario Rossi" and public["logo"] is None

    # A comune's coat of arms keeps the institutional licence; a photo cannot claim it.
    logo = client.post("/redazione/api/immagini", headers=ANNA, json={"data": _photo((200, 20, 20), (900, 900)), "purpose": "logo"}).json()
    assert logo["width"] == 640
    wrong = client.post("/redazione/api/simboli", headers=ANNA, json={
        "kind": "municipality_photo", "key": str(ids["municipality"]), "image_id": logo["id"], "credit": "Comune",
        "license": "istituzionale", "source_url": "https://www.comune.milano.it/stemma",
    })
    assert wrong.status_code == 422
    arms = client.post("/redazione/api/simboli", headers=ANNA, json={
        "kind": "municipality", "key": str(ids["municipality"]), "image_id": logo["id"], "credit": "Comune di Milano",
        "license": "istituzionale", "source_url": "https://www.comune.milano.it/stemma",
    }).json()
    client.post(f"/redazione/api/coda/change/{arms['id']}/approva", headers=BRUNO, json={})
    assert client.get(f"/territories/municipality/{ids['municipality']}").json()["images"]["logo"]["url"] == logo["url"]


def test_editorial_holder_overlay_does_not_invent_a_dait_mandate(console):
    client, ids = console
    path = f"/redazione/api/territori/municipality/{ids['municipality']}/blocchi/titolare"
    wikipedia = client.post(
        path,
        headers=ANNA,
        json={
            "fields": {"nome": "Giuseppe Sala", "in_carica_dal": "2021-10-18"},
            "sources": [{"name": "Wikipedia", "url": "https://it.wikipedia.org/wiki/Giuseppe_Sala"}],
        },
    )
    assert wikipedia.status_code == 200, wikipedia.text
    blocked = next(item for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "territory")
    assert blocked["blocked"] is True
    assert any(finding["code"] == "fonte_secondaria" for finding in blocked["findings"])
    official = client.post(
        path,
        headers=ANNA,
        json={
            "fields": {"nome": "Giuseppe Sala", "in_carica_dal": "2021-10-18"},
            "sources": [{"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco"}],
        },
    )
    assert official.status_code == 200, official.text
    item = next(item for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "territory" and not item["blocked"])
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    assert public["base"]["holder"]["name"] == "Giuseppe Sala"
    assert public["base"]["holder"]["editorial"] is True
    assert public["base"]["holder"]["politician_id"] is None
    assert all(block["key"] != "titolare" for block in public["blocks"])
    with client.app.state.session_factory() as session:
        assert list(session.scalars(select(TerritorialOfficeMandate))) == []


def test_giunta_consiglio_and_coalition_options(console):
    client, ids = console
    base = f"/redazione/api/territori/region/{ids['region']}/blocchi"
    giunta = client.post(
        f"{base}/giunta",
        headers=ANNA,
        json={
            "rows": [
                {"ruolo": "presidente", "nome": "Attilio Fontana", "partito": "Lega", "delega": "Coordinamento"},
                {"ruolo": "assessore", "nome": "Guido Bertolaso", "partito": "Indipendente", "delega": "Welfare"},
            ],
            "sources": [{"name": "Regione Lombardia", "url": "https://www.regione.lombardia.it/wps/portal/istituzionale/HP/istituzione/Giunta/composizione"}],
        },
    )
    assert giunta.status_code == 200, giunta.text
    item = next(row for row in client.get("/redazione/api/coda", headers=BRUNO).json() if row["kind"] == "territory")
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=BRUNO, json={}).status_code == 200
    consiglio = client.post(
        f"{base}/consiglio",
        headers=ANNA,
        json={
            "rows": [
                {"gruppo": "Lega", "consiglieri": "29", "capogruppo": "Rossi", "sostiene_giunta": "si"},
                {"gruppo": "PD", "consiglieri": "17", "capogruppo": "Bianchi", "sostiene_giunta": "no"},
            ],
            "sources": [{"name": "Consiglio regionale Lombardia", "url": "https://www.consiglio.regione.lombardia.it/groups/consiglieri"}],
        },
    )
    assert consiglio.status_code == 200, consiglio.text
    pending = next(row for row in client.get("/redazione/api/coda", headers=BRUNO).json() if row["kind"] == "territory")
    assert client.post(f"/redazione/api/coda/territory/{pending['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get(f"/territories/region/{ids['region']}").json()
    giunta_block = next(block for block in public["blocks"] if block["key"] == "giunta")
    assert giunta_block["data"]["rows"][0]["ruolo"] == "presidente"
    assert giunta_block["data"]["rows"][0]["partito"] == "Lega"
    consiglio_block = next(block for block in public["blocks"] if block["key"] == "consiglio")
    assert consiglio_block["type"] == "rows" and consiglio_block["data"]["rows"][0]["gruppo"] == "Lega"
    # New coalition keys are accepted.
    client.post(
        f"{base}/rapida",
        headers=ANNA,
        json={"fields": {"capoluogo": "Milano", "coalizione": "autonomista"}, "sources": [ISTAT]},
    )
    draft = next(row for row in client.get("/redazione/api/coda", headers=BRUNO).json() if row["kind"] == "territory")
    assert draft["preview"]["data"]["coalizione"] == "autonomista"


def test_roma_municipi_hub_and_scheda(console):
    client, ids = console
    catalog = client.get("/territories/municipi/roma").json()
    assert len(catalog["items"]) == 15
    assert catalog["items"][0]["key"] == "roma-1" and catalog["items"][-1]["key"] == "roma-15"
    scheda = client.get("/redazione/api/territori/municipio/roma-3", headers=ANNA).json()
    assert scheda["base"]["title"] == "Roma — Municipio III"
    assert scheda["base"]["roman"] == "III"
    assert [block["key"] for block in scheda["definitions"] if not block.get("hidden")][:4] == [
        "rapida", "utile", "indirizzo", "come_funziona",
    ]
    public = client.get("/territories/municipio/roma-3").json()
    assert public["base"]["key"] == "roma-3"
    assert public["base"]["municipi"][2]["key"] == "roma-3"
    assert client.get("/territories/municipio/roma-99").status_code == 404
