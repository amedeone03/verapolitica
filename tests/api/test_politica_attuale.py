"""«Politica attuale»: the redazione corrects what Politica shows; the official value stays alongside."""

from datetime import date

from sqlalchemy.orm import Session

from backend.app.models import ParliamentaryGroup, Politician, RawDocument, Source
from backend.app.models.parliamentary_group_membership import ParliamentaryGroupMembership
from backend.app.services import normalize_person_name
from tests.api.test_territory_schede import ANNA, BRUNO, CARLA, _client

SOURCE = [{"name": "Camera dei deputati, composizione dei gruppi", "url": "https://www.camera.it/leg19/46?shadow_organo_parlamentare=2809"}]


def _groups(engine):
    with Session(engine) as session:
        source = session.query(Source).first()
        document = session.query(RawDocument).first()
        group = ParliamentaryGroup(canonical_name="Gruppo ufficiale", abbreviation="GU", institution="Camera dei Deputati", legislature="XIX")
        session.add(group)
        session.flush()
        for index in range(3):
            person = Politician(canonical_given_name="P", canonical_family_name=f"N{index}", normalized_name=normalize_person_name("P", f"N{index}"))
            session.add(person)
            session.flush()
            session.add(ParliamentaryGroupMembership(politician_id=person.id, parliamentary_group_id=group.id, source_id=source.id, raw_document_id=document.id, identity_key=f"k{index}", source_url="https://dati.camera.it/x", start_date=date(2022, 10, 13)))
        session.commit()
        return group.id


def test_a_correction_waits_for_the_admin_then_replaces_the_official_value(tmp_path):
    client, ids, engine = _client(tmp_path, admins="Carla Caporedattrice")
    group_id = _groups(engine)
    with client:
        key = f"chamber:camera:group:{group_id}"
        saved = client.post(f"/redazione/api/politica/{key}", headers=ANNA, json={"seats": 4, "name": "Gruppo corretto", "sources": SOURCE, "reason": "Un deputato è entrato nel gruppo il 3 novembre 2026."})
        assert saved.status_code == 200 and saved.json().get("published") is not True
        # Nothing changes on the site until an admin publishes.
        assert client.get("/parliament/composition").json()["camera"]["groups"][0]["seats"] == 3
        item = next(item for item in client.get("/redazione/api/coda", headers=CARLA).json() if item["kind"] == "politica")
        assert item["title"] == "Politica attuale — Camera" and not item["blocked"]
        assert client.post(f"/redazione/api/coda/politica/{item['id']}/approva", headers=CARLA, json={}).status_code == 200
        camera = client.get("/parliament/composition").json()["camera"]
        group = camera["groups"][0]
        assert group["seats"] == 4 and group["name"] == "Gruppo corretto"
        assert group["official"] == {"name": "Gruppo ufficiale", "abbreviation": "GU", "seats": 3}
        assert camera["counted"] == 4 and camera["majority"] == 3
        # An admin adds a group the official data lacks; it is published at once.
        added = client.post("/redazione/api/politica/chamber:camera:extra:nuovo-gruppo", headers=CARLA, json={"name": "Nuovo gruppo", "seats": 2, "sources": SOURCE, "reason": "Costituito il 4 novembre 2026."}).json()
        assert added["published"] is True
        camera = client.get("/parliament/composition").json()["camera"]
        assert [group["name"] for group in camera["groups"]] == ["Gruppo corretto", "Nuovo gruppo"]
        # Back to the official value.
        client.post(f"/redazione/api/politica/{key}", headers=CARLA, json={"restore": True, "reason": "Il sito ufficiale è aggiornato."})
        assert client.get("/parliament/composition").json()["camera"]["groups"][0]["seats"] == 3
    engine.dispose()


def test_rules_reason_and_source_are_required(tmp_path):
    client, ids, engine = _client(tmp_path)
    with client:
        client.post(f"/redazione/api/politica/region:{ids['region']}", headers=ANNA, json={"coalition": "centrodestra"})
        item = next(item for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "politica")
        codes = {finding["code"] for finding in item["findings"]}
        assert {"motivo_mancante", "fonte_mancante"} <= codes and item["blocked"]
        assert client.post("/redazione/api/politica/nonsense:1", headers=ANNA, json={}).status_code == 404
        # The console page lists live corrections and open versions.
        page = client.get("/redazione/api/politica", headers=ANNA).json()
        assert f"region:{ids['region']}" in page["pending"] and page["published"] == {}
        assert page["tiers"]["0"] == "Presidente del Consiglio"
    engine.dispose()


def test_region_corrections_reach_the_overview_and_edits_are_public(tmp_path):
    client, ids, engine = _client(tmp_path, admins="Carla Caporedattrice")
    with client:
        client.post(f"/redazione/api/politica/region:{ids['region']}", headers=CARLA, json={
            "coalition": "centrodestra", "president_name": "Attilio Fontana", "next_election": "Primavera 2028",
            "sources": [{"name": "Regione Lombardia", "url": "https://www.regione.lombardia.it/wps/portal/istituzionale/HP/istituzione/Giunta/presidente"}],
            "reason": "Il presidente non è ancora collegato all'anagrafe ufficiale.",
        })
        client.post("/redazione/api/politica/government:1", headers=CARLA, json={"party_name": "Partito di prova", "tier": "2", "sources": SOURCE, "reason": "Affiliazione mancante nei dati importati."})
        client.post("/redazione/api/politica/text:government_note", headers=CARLA, json={"body": "Nota della redazione.", "reason": "Testo più chiaro."})
        region = client.get("/territories/regions").json()
        lombardia = region["items"][0]
        assert lombardia["coalition"] == "centrodestra" and lombardia["president"]["name"] == "Attilio Fontana"
        assert lombardia["official"]["president"] is None and lombardia["edited"]["reason"].startswith("Il presidente")
        assert region["counts"]["centrodestra"] == 1
        edits = client.get("/parliament/edits").json()["items"]
        assert edits["government:1"]["party_name"] == "Partito di prova" and edits["government:1"]["tier"] == "2"
        assert edits["text:government_note"]["body"] == "Nota della redazione."
    engine.dispose()
