"""Regione, Provincia, Comune: the redazione writes the model's blocks on top of the official base."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Municipality, RawDocument, RawDocumentStatus, Region, Source

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
    assert [block["key"] for block in region["definitions"]] == ["rapida", "presidente", "giunta", "consiglio", "promesse", "elezioni"]
    assert region["base"]["name"] == "Lombardia" and region["base"]["municipality_count"] == 1
    assert region["base"]["provinces"] == [{"abbreviation": "MI", "name": "Milano", "municipalities": 1}]
    town = client.get(f"/redazione/api/territori/municipality/{ids['municipality']}", headers=ANNA).json()
    assert [block["title"] for block in town["definitions"]] == ["Scheda rapida", "Il sindaco", "La giunta", "Consiglio e opposizione", "Promesse del mandato", "Elezioni (storico e prossime)"]
    assert town["base"]["province"] == {"abbreviation": "MI", "name": "Milano"}
    province = client.get("/redazione/api/territori/province/mi", headers=ANNA).json()
    assert province["base"]["name"] == "Milano" and province["base"]["key"] == "MI"
    assert client.get("/redazione/api/territori/region/999", headers=ANNA).status_code == 404
    # The console finds territories by name.
    found = client.get("/redazione/api/territori?q=mil", headers=ANNA).json()
    assert {row["kind"] for row in found} == {"province", "municipality"}


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
    assert public["blocks"][1]["data"] is None
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/territory/{item['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    sindaco = public["blocks"][1]
    assert sindaco["data"]["body"] == body and sindaco["written_by"] == "Anna Redattrice" and sindaco["published_by"] == "Bruno Verificatore"
    assert {"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco", "date": None} in public["sources"]
    # A published block can always be changed: the new version replaces it once approved.
    client.post(path, headers=BRUNO, json={"body": body.replace("giugno 2016", "1° luglio 2016"), "sources": [{"name": "Comune di Milano", "url": "https://www.comune.milano.it/comune/sindaco"}]})
    second = next(item for item in client.get("/redazione/api/coda", headers=ANNA).json() if item["kind"] == "territory")
    client.post(f"/redazione/api/coda/territory/{second['id']}/approva", headers=ANNA, json={})
    public = client.get(f"/territories/municipality/{ids['municipality']}").json()
    assert "1° luglio 2016" in public["blocks"][1]["data"]["body"]
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
        assert empty["counts"] == {"centrosinistra": 0, "centrodestra": 0, "altro": 0, "da_compilare": 1}
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
