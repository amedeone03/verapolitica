"""The redazione console: who writes, who verifies, what the citizen sees.

Covers the rules of the "Modelli di scrittura" that the console enforces and
the path from an editor's draft to the public profile and the scorecard.
"""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    EditorialLogEntry,
    ImmutableEditorialLogError,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    Source,
)
from backend.app.services import normalize_person_name

ANNA = {"Authorization": "Bearer tok-anna-redattrice"}
BRUNO = {"Authorization": "Bearer tok-bruno-verificatore"}
CARLA = {"Authorization": "Bearer tok-carla-caporedattrice"}
MEMBERS = "Anna Redattrice=tok-anna-redattrice;Bruno Verificatore=tok-bruno-verificatore;Carla Caporedattrice=tok-carla-caporedattrice"
NOW = datetime(2026, 10, 31, 9, tzinfo=timezone.utc)
SOURCE = {"name": "Camera dei deputati", "url": "https://www.camera.it/leg19/1?shadow_deputato=306970", "area": "istituzionale"}
CLASSIFICATION = {
    "specificity": "high",
    "commitment_type": "action",
    "holder_role": "government_coalition",
    "cap_topic_code": "13",
    "mandate_start": "2022-10-22",
    "mandate_end": "2027-10-22",
}


def _seed(factory) -> int:
    with factory() as session:
        source = Source(key="camera-deputati", name="Camera dei Deputati", base_url="https://dati.camera.it")
        session.add(source)
        session.flush()
        politician = Politician(
            canonical_given_name="Mario",
            canonical_family_name="Esempio",
            normalized_name=normalize_person_name("Mario", "Esempio"),
            birth_date=date(1970, 1, 1),
        )
        session.add(politician)
        session.flush()
        version = PoliticianVersion(
            politician_id=politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data={"given_name": "Mario", "family_name": "Esempio", "mandates": []},
            published_at=NOW,
        )
        session.add(version)
        session.flush()
        politician.current_version = version
        session.add(PoliticianSourceIdentifier(politician_id=politician.id, source_id=source.id, value="deputato:esempio"))
        session.commit()
        return politician.id


@pytest.fixture
def console(tmp_path):
    url = f"sqlite:///{tmp_path / 'redazione.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    politician_id = _seed(factory)
    settings = Settings(
        database_url=url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="redazione-admin",
        redazione_members=MEMBERS,
    )
    with TestClient(create_app(settings)) as client:
        yield client, politician_id, factory
    engine.dispose()


def _queue_item(client, headers, kind, **match):
    for item in client.get("/redazione/api/coda", headers=headers).json():
        if item["kind"] == kind and all(item.get(key) == value for key, value in match.items()):
            return item
    raise AssertionError(f"{kind} {match} not in queue")


def test_members_sign_in_with_their_own_token(console):
    client, _, _ = console
    assert client.get("/redazione/api/me").status_code == 401
    assert client.get("/redazione/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    me = client.get("/redazione/api/me", headers=ANNA).json()
    assert me["name"] == "Anna Redattrice"
    assert me["members"] == ["Anna Redattrice", "Bruno Verificatore", "Carla Caporedattrice"]
    assert client.get("/redazione/").status_code == 200


def test_profile_block_needs_a_second_person_and_no_open_brackets(console):
    client, politician_id, factory = console
    base = f"/redazione/api/politici/{politician_id}"
    body = "Mario Esempio è deputato dal 2018. Laureato in giurisprudenza, avvocato. [anno di laurea]"
    saved = client.post(f"{base}/blocchi/biography", headers=ANNA, json={"body": body, "sources": [SOURCE]})
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["status"] == "pending"
    assert any(f["code"] == "parentesi_aperte" for f in item["findings"])

    queued = _queue_item(client, BRUNO, "biography")
    assert queued["blocked"] and not queued["can_approve"]
    blocked = client.post(f"/redazione/api/coda/biography/{item['id']}/approva", headers=BRUNO, json={})
    assert blocked.status_code == 422

    # The writer fixes the draft; nothing is public yet.
    fixed = client.post(
        f"{base}/blocchi/biography",
        headers=ANNA,
        json={"identity_key": "primary", "body": body.replace(" [anno di laurea]", ""), "sources": [SOURCE]},
    ).json()
    assert fixed["id"] == item["id"]
    assert client.get(f"/politicians/{politician_id}").json()["biography"] is None

    own = client.post(f"/redazione/api/coda/biography/{item['id']}/approva", headers=ANNA, json={})
    assert own.status_code == 409
    assert "Chi scrive non è chi verifica" in own.json()["detail"]

    ok = client.post(f"/redazione/api/coda/biography/{item['id']}/approva", headers=BRUNO, json={"note": "Fonti controllate."})
    assert ok.status_code == 200, ok.text
    public = client.get(f"/politicians/{politician_id}").json()
    assert public["biography"]["body"].startswith("Mario Esempio è deputato dal 2018.")
    assert public["editorial"]["written_by"] == ["Anna Redattrice"]
    assert public["editorial"]["verified_by"] == ["Bruno Verificatore"]

    scheda = client.get(base, headers=CARLA).json()
    assert scheda["scheda_rapida"]["writers"] == ["Anna Redattrice"]
    assert scheda["scheda_rapida"]["verifiers"] == ["Bruno Verificatore"]

    # Withdrawing what the citizen sees is itself a change another person approves.
    withdraw = client.post(
        f"/redazione/api/contenuti/biography/{item['id']}/ritira", headers=ANNA, json={"reason": "Data di laurea da riverificare."}
    ).json()
    assert client.post(f"/redazione/api/coda/change/{withdraw['id']}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/change/{withdraw['id']}/approva", headers=CARLA, json={}).status_code == 200
    assert client.get(f"/politicians/{politician_id}").json()["biography"] is None

    log = client.get("/redazione/api/registro", headers=ANNA).json()
    actions = [entry["action"] for entry in reversed(log["items"])]
    assert actions == ["scrittura", "modifica", "approvazione", "richiesta_ritiro", "approvazione"]
    assert log["items"][-2]["details"]["before"]["body"].endswith("[anno di laurea]")
    with factory() as session:
        entry = session.scalars(select(EditorialLogEntry)).first()
        entry.summary = "riscritto"
        with pytest.raises(ImmutableEditorialLogError):
            session.flush()


def test_promise_status_drives_the_scorecard(console):
    client, politician_id, _ = console
    base = f"/redazione/api/politici/{politician_id}"

    def promise(title, statement):
        response = client.post(
            f"{base}/promesse",
            headers=ANNA,
            json={
                "title": title,
                "exact_statement": statement,
                "introduced_at": "2022-10-25",
                "where": "Discorso alla Camera per la fiducia",
                "source": {"name": "Camera dei deputati", "url": "https://www.camera.it/leg19/410?idSeduta=0002"},
                "classification": CLASSIFICATION,
            },
        )
        assert response.status_code == 200, response.text
        created = response.json()
        assert client.post(f"/redazione/api/coda/promise/{created['draft_id']}/approva", headers=ANNA, json={}).status_code == 409
        assert client.post(f"/redazione/api/coda/promise/{created['draft_id']}/approva", headers=BRUNO, json={}).status_code == 200
        return created["proposal_id"]

    first = promise("Aumentare le pensioni minime", "Porteremo le pensioni minime a 1.000 euro al mese.")
    second = promise("Ridurre le accise sui carburanti", "Taglieremo le accise sui carburanti entro il 2023.")
    card = client.get(f"/politicians/{politician_id}/scorecard").json()
    assert card["tracked_pledges"] == 2 and card["unclassified_pledges"] == 0
    assert {item["verdict"] for item in card["pledges"]} == {"not_yet_rated"}

    kept = client.post(
        f"/redazione/api/promesse/{first}/stato",
        headers=ANNA,
        json={
            "verdict": "kept",
            "rationale": "La legge di bilancio 2025 ha portato le pensioni minime a 1.000 euro dal 1° gennaio 2025.",
            "quoted_excerpt": "le pensioni minime sono aumentate a 1.000 euro mensili dal 1° gennaio 2025",
            "effective_at": "2025-01-01",
            "source": {"name": "Gazzetta Ufficiale", "url": "https://www.gazzettaufficiale.it/eli/id/2024/12/31/24G00218/sg"},
        },
    )
    assert kept.status_code == 200, kept.text
    status_id = kept.json()["draft_id"]
    # Pending verdicts never reach the scorecard.
    assert all(p["verdict"] == "not_yet_rated" for p in client.get(f"/politicians/{politician_id}/scorecard").json()["pledges"])
    assert client.post(f"/redazione/api/coda/status/{status_id}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/status/{status_id}/approva", headers=BRUNO, json={}).status_code == 200

    broken_payload = {
        "verdict": "broken",
        "rationale": "Le accise non sono state ridotte nel 2023.",
        "quoted_excerpt": "Le aliquote di accisa sui carburanti restano invariate per tutto il 2023",
        "effective_at": "2024-01-02",
        "source": {"name": "Agenzia delle Dogane", "url": "https://www.adm.gov.it/portale/-/accise-carburanti-2023"},
    }
    no_reason = client.post(f"/redazione/api/promesse/{second}/stato", headers=ANNA, json=broken_payload)
    assert no_reason.status_code == 422 and "scadenza" in no_reason.json()["detail"]
    late = client.post(
        f"/redazione/api/promesse/{second}/stato",
        headers=ANNA,
        json={**broken_payload, "broken_reason": "scadenza_passata", "deadline": "2024-06-30"},
    )
    assert late.status_code == 422
    broken = client.post(
        f"/redazione/api/promesse/{second}/stato",
        headers=ANNA,
        json={**broken_payload, "broken_reason": "scadenza_passata", "deadline": "2023-12-31"},
    )
    assert broken.status_code == 200, broken.text
    assert broken.json()["approvals_required"] == 2
    broken_id = broken.json()["draft_id"]
    assert client.post(f"/redazione/api/coda/status/{broken_id}/approva", headers=BRUNO, json={}).status_code == 200
    item = _queue_item(client, BRUNO, "status", id=broken_id)
    assert item["approvals"] == ["Bruno Verificatore"] and not item["can_approve"]
    assert client.post(f"/redazione/api/coda/status/{broken_id}/approva", headers=BRUNO, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/status/{broken_id}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/status/{broken_id}/approva", headers=CARLA, json={}).status_code == 200

    card = client.get(f"/politicians/{politician_id}/scorecard").json()
    verdicts = {item["proposal_id"]: item["verdict"] for item in card["pledges"]}
    assert verdicts == {first: "kept", second: "broken"}
    stratum = card["strata"][0]
    assert stratum["role"] == "government_coalition"
    assert stratum["closed_pledges"] == 2 and stratum["kept_equivalent"] == 1
    # Below eight closed promises the rate is withheld, as in the methodology.
    assert stratum["rate"] is None and stratum["rate_withheld_reason"] == "below_minimum_closed_pledges"
    broken_row = next(item for item in card["pledges"] if item["proposal_id"] == second)
    assert broken_row["latest_assessment"]["rationale"].startswith("La scadenza dichiarata è passata")

    # Re-classifying (vague: excluded from the score) waits for approval too.
    change = client.post(
        f"/redazione/api/promesse/{second}/classificazione", headers=ANNA, json={**CLASSIFICATION, "specificity": "vague"}
    ).json()
    assert client.get(f"/politicians/{politician_id}/scorecard").json()["excluded_vague_pledges"] == 0
    assert client.post(f"/redazione/api/coda/change/{change['id']}/approva", headers=BRUNO, json={}).status_code == 200
    assert client.get(f"/politicians/{politician_id}/scorecard").json()["excluded_vague_pledges"] == 1


def test_news_follows_the_nine_block_model(console):
    client, politician_id, _ = console
    blocks = {
        "sommario": "Il Consiglio dei ministri ha approvato il 16 settembre 2026 un decreto-legge sul bollo auto.",
        "perche": "Il bollo riguarda la gran parte degli automobilisti e il decreto va convertito entro il 16 novembre.",
        "fatto": "Il Consiglio dei ministri ha approvato un decreto-legge che azzera il bollo 2027 per una sola auto fino a 80 kW.",
        "perche_deciso": "Secondo il Governo, per alleggerire il costo dell'auto usata ogni giorno.",
        "cosa_cambia": "- Una sola auto fino a 80 kW: non paghi il bollo nel 2027.\n- Auto sopra i 185 kW: continui a pagare.",
        "destra": "- Fratelli d'Italia: misura pensata per essere strutturale.\n- Lega: valuta anche il superbollo.",
        "sinistra": "- Partito Democratico: misura limitata al 2027.\n- Movimento 5 Stelle: il risparmio medio è basso.",
        "altri": "Azione ha definito l'abolizione «cosa buona e giusta».",
        "numeri": "Costo 2027: 2,2935 miliardi di euro secondo il testo del decreto.",
        "cosa_succede": "Il decreto va convertito in legge entro il 16 novembre 2026.",
    }
    one_source = {
        "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
        "blocks": blocks,
        "sources": [{"name": "ANSA", "url": "https://www.ansa.it/sito/notizie/economia/2026/09/16/bollo-auto.html", "area": "agenzia"}],
        "politician_ids": [politician_id],
    }
    created = client.post("/redazione/api/notizie", headers=ANNA, json=one_source)
    assert created.status_code == 200, created.text
    post = created.json()
    assert any(f["code"] == "fonti_varie" for f in post["findings"])
    assert client.post(f"/redazione/api/coda/news/{post['id']}/approva", headers=BRUNO, json={}).status_code == 422

    sources = one_source["sources"] + [
        {"name": "Il Giornale", "url": "https://www.ilgiornale.it/news/politica/bollo-auto-2027.html", "area": "centrodestra"},
        {"name": "Domani", "url": "https://www.editorialedomani.it/politica/bollo-auto-2027-esenzione", "area": "centrosinistra"},
    ]
    updated = client.put(f"/redazione/api/notizie/{post['id']}", headers=ANNA, json={**one_source, "sources": sources}).json()
    assert not any(f["level"] == "error" for f in updated["findings"])
    assert client.post(f"/redazione/api/coda/news/{post['id']}/approva", headers=ANNA, json={}).status_code == 409
    assert client.post(f"/redazione/api/coda/news/{post['id']}/approva", headers=BRUNO, json={}).status_code == 200

    public = client.get(f"/feed/posts/{post['id']}").json()
    assert public["blocks"]["fatto"].startswith("Il Consiglio dei ministri")
    assert [source["title"] for source in public["sources"]] == ["ANSA", "Il Giornale", "Domani"]
    assert public["written_by"] == "Anna Redattrice" and public["verified_by"] == "Bruno Verificatore"
    profile = client.get(f"/politicians/{politician_id}").json()
    assert [item["id"] for item in profile["editorial"]["related_posts"]] == [post["id"]]

    assert client.post(f"/redazione/api/coda/news/{post['id']}/rifiuta", headers=CARLA, json={"note": "x"}).status_code == 404
    assert client.put(f"/redazione/api/notizie/{post['id']}", headers=ANNA, json=one_source).status_code == 409


def test_rejection_needs_a_reason_and_is_logged(console):
    client, politician_id, _ = console
    item = client.post(
        f"/redazione/api/politici/{politician_id}/blocchi/position",
        headers=ANNA,
        json={
            "topic": "Fisco",
            "position_statement": "Ha proposto di ridurre l'IRPEF per i redditi medi.",
            "verifiable_statement": "Intervento in Aula del 12 marzo 2025.",
            "statement_date": "2025-03-12",
            "sources": [SOURCE],
        },
    ).json()
    assert client.post(f"/redazione/api/coda/position/{item['id']}/rifiuta", headers=BRUNO, json={}).status_code == 422
    assert client.post(
        f"/redazione/api/coda/position/{item['id']}/rifiuta", headers=BRUNO, json={"note": "Manca il resoconto."}
    ).status_code == 200
    log = client.get(f"/redazione/api/registro?politico={politician_id}", headers=ANNA).json()["items"]
    assert log[0]["action"] == "rifiuto" and "Manca il resoconto." in log[0]["summary"]
    assert log[0]["actor"] == "Bruno Verificatore"
