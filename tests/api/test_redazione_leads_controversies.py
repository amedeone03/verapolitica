"""Capi squadra verify their own work; controversies are kept apart from proceedings."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import DEMO_REDAZIONE_MEMBERS, Settings
from backend.app.db.base import Base
from backend.app.db.schema import prepare_sqlite_schema
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import EditorialLogEntry, PoliticianProceeding
from tests.api.test_redazione_console import ANNA, BRUNO, CARLA, MEMBERS, SOURCE, _queue_item, _seed

# Test data, same shape as test_news_follows_the_nine_block_model.
NEWS = {
    "title": "Bollo auto 2027: esenzione per una sola auto fino a 80 kW",
    "blocks": {
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
    },
    "sources": [
        {"name": "ANSA", "url": "https://www.ansa.it/sito/notizie/economia/2026/09/16/bollo-auto.html", "area": "agenzia"},
        {"name": "Il Giornale", "url": "https://www.ilgiornale.it/news/politica/bollo-auto-2027.html", "area": "centrodestra"},
        {"name": "Domani", "url": "https://www.editorialedomani.it/politica/bollo-auto-2027-esenzione", "area": "centrosinistra"},
    ],
}
SENATO = {"name": "Senato della Repubblica", "url": "https://www.senato.it/leg19/resoconto", "area": "istituzionale"}


@pytest.fixture
def desk(tmp_path):
    url = f"sqlite:///{tmp_path / 'leads.db'}"
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    politician_id = _seed(factory)
    settings = Settings(
        database_url=url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="redazione-admin",
        redazione_members=MEMBERS,
        redazione_leads="Carla Caporedattrice; Nessuno Sconosciuto",
    )
    with TestClient(create_app(settings)) as client:
        yield client, politician_id, factory
    engine.dispose()


def _biography(politician_id: int) -> dict:
    return {
        "body": "Mario Esempio è nato nel 1970. È deputato dalla XIX legislatura e siede nella commissione Bilancio.",
        "sources": [SOURCE],
    }


def test_only_named_members_are_capi_squadra():
    settings = Settings(redazione_members=MEMBERS, redazione_leads="Carla Caporedattrice;Nessuno Sconosciuto")
    assert settings.redazione_lead_names == {"Carla Caporedattrice"}
    assert Settings(redazione_members=MEMBERS).redazione_lead_names == frozenset()
    demo = Settings(enable_demo_ui=True)
    assert set(demo.redazione_member_tokens.values()) == set(DEMO_REDAZIONE_MEMBERS.values())
    assert demo.redazione_lead_names == {"Caporedattore demo"}


def test_a_capo_squadra_verifies_their_own_block_and_the_log_says_so(desk):
    client, politician_id, factory = desk
    assert client.get("/redazione/api/me", headers=CARLA).json()["lead"] is True
    assert client.get("/redazione/api/me", headers=ANNA).json()["lead"] is False

    saved = client.post(f"/redazione/api/politici/{politician_id}/blocchi/biography", headers=CARLA, json=_biography(politician_id)).json()
    queued = _queue_item(client, CARLA, "biography", id=saved["id"])
    assert queued["own"] and queued["can_self_verify"] and not queued["can_approve"]
    approved = client.post(f"/redazione/api/coda/biography/{saved['id']}/approva", headers=CARLA, json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["self_verified"] is True
    assert client.get(f"/politicians/{politician_id}").json()["biography"] is not None
    with factory() as session:
        entry = session.scalars(
            select(EditorialLogEntry).where(EditorialLogEntry.action == "approvazione").order_by(EditorialLogEntry.id.desc())
        ).first()
    assert entry.actor == "Carla Caporedattrice" and entry.details["self_verified"] is True
    assert "capo squadra" in entry.summary

    # Anyone else still needs a second person.
    other = client.post(f"/redazione/api/politici/{politician_id}/blocchi/career_entry", headers=ANNA, json={
        "role": "Deputato", "institution": "Camera dei deputati", "start_date": "2022-10-13", "sources": [SOURCE],
    }).json()
    assert not _queue_item(client, ANNA, "career_entry", id=other["id"])["can_self_verify"]
    refused = client.post(f"/redazione/api/coda/career_entry/{other['id']}/approva", headers=ANNA, json={})
    assert refused.status_code == 409 and "Chi scrive non è chi verifica" in refused.json()["detail"]


def test_a_capo_squadra_publishes_a_new_politician_at_once(desk):
    client, _, _ = desk
    payload = {
        "given_name": "Giorgia", "family_name": "Meloni", "birth_date": "1977-01-15",
        "source_url": "https://www.governo.it/it/presidente", "office": "presidente del consiglio",
        "start_date": "2022-10-22", "publish_now": True,
    }
    # «Pubblica subito» from someone who is not a capo squadra only saves the proposal.
    anna = client.post("/redazione/api/politici", headers=ANNA, json={**payload, "family_name": "Rossi"}).json()
    assert "published" not in anna
    assert not any(row["family_name"] == "Rossi" for row in client.get("/politicians").json()["items"])

    carla = client.post("/redazione/api/politici", headers=CARLA, json=payload)
    assert carla.status_code == 200, carla.text
    assert carla.json()["published"] is True
    assert any(row["family_name"] == "Meloni" for row in client.get("/politicians").json()["items"])
    assert not any(item["id"] == carla.json()["id"] for item in client.get("/redazione/api/coda", headers=BRUNO).json() if item["kind"] == "change")


def test_a_capo_squadra_publishes_a_news_item_directly(desk):
    client, _, _ = desk
    created = client.post("/redazione/api/notizie", headers=CARLA, json={**NEWS, "publish_now": True})
    assert created.status_code == 200, created.text
    assert created.json()["published"] is True


def test_controversies_are_a_separate_box_from_proceedings(desk):
    client, politician_id, _ = desk
    base = f"/redazione/api/politici/{politician_id}/blocchi/proceeding"
    controversy = client.post(base, headers=ANNA, json={
        "category": "controversy",
        "title": "Indagine sul figlio",
        "proceeding_types": ["related_investigation"],
        "event_date": "2023-07-07",
        "summary": "La procura di Milano indaga il figlio di Mario Esempio. Mario Esempio non è indagato.",
        "sources": [SENATO],
    })
    assert controversy.status_code == 200, controversy.text
    assert controversy.json()["data"]["category"] == "controversy"
    assert _queue_item(client, BRUNO, "proceeding", id=controversy.json()["id"])["kind_label"] == "Controversia"

    # An investigation of the politician cannot hide among controversies, and vice versa.
    wrong = client.post(base, headers=ANNA, json={
        "category": "controversy", "title": "Indagine", "proceeding_types": ["investigation"],
        "summary": "Testo.", "sources": [SENATO],
    })
    assert wrong.status_code == 422 and "Procedimenti giudiziari" in wrong.json()["detail"]
    wrong = client.post(base, headers=ANNA, json={
        "category": "proceeding", "title": "Busto", "proceeding_types": ["media_controversy"],
        "summary": "Testo.", "sources": [SENATO],
    })
    assert wrong.status_code == 422 and "Controversie" in wrong.json()["detail"]

    proceeding = client.post(base, headers=ANNA, json={
        "category": "proceeding", "title": "Processo per diffamazione",
        "proceeding_types": ["judicial_proceeding"], "event_date": "2021-03-01", "outcome": "ongoing",
        "summary": "Il tribunale di Roma ha rinviato a giudizio Mario Esempio per diffamazione nel 2021.",
        "sources": [SENATO],
    }).json()
    for item in (controversy.json(), proceeding):
        assert client.post(f"/redazione/api/coda/proceeding/{item['id']}/approva", headers=BRUNO, json={}).status_code == 200
    public = client.get(f"/politicians/{politician_id}").json()["proceedings"]
    assert {item["title"]: item["category"] for item in public} == {
        "Indagine sul figlio": "controversy",
        "Processo per diffamazione": "proceeding",
    }


def test_old_rows_are_sorted_into_the_right_box(tmp_path):
    """SQLite demos built before the column: controversy-only rows become controversies."""

    import sqlite3

    path = tmp_path / "old.db"
    engine = create_db_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    politician_id = _seed(create_session_factory(engine))
    engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE politician_proceedings DROP COLUMN category")
        for title, types in (("Busto", '["media_controversy"]'), ("Processo", '["judicial_proceeding","media_controversy"]')):
            connection.execute(
                "INSERT INTO politician_proceedings (politician_id, identity_key, status, created_by, created_at, updated_at, "
                "title, proceeding_types, summary) VALUES (?, ?, 'pending', 'x', '2026-01-01', '2026-01-01', ?, ?, 's')",
                (politician_id, title.lower(), title, types),
            )
    engine = create_db_engine(f"sqlite:///{path}")
    prepare_sqlite_schema(engine)
    with create_session_factory(engine)() as session:
        rows = {row.title: row.category for row in session.scalars(select(PoliticianProceeding))}
    engine.dispose()
    assert rows == {"Busto": "controversy", "Processo": "proceeding"}


def test_overview_counts_the_week_and_the_schede_with_a_biography(desk):
    client, politician_id, _ = desk
    before = client.get("/redazione/api/panoramica", headers=CARLA).json()
    assert before["public_schede"] == 1 and before["schede_with_bio"] == 0
    saved = client.post(f"/redazione/api/politici/{politician_id}/blocchi/biography", headers=CARLA, json={**_biography(politician_id), "publish_now": True}).json()
    assert saved["published"] is True
    after = client.get("/redazione/api/panoramica", headers=CARLA).json()
    assert after["schede_with_bio"] == 1
    assert after["published_week"] == before["published_week"] + 1
    assert after["my_published_week"] == before["my_published_week"] + 1


def test_home_lists_my_rejections_until_i_save_again(desk):
    client, politician_id, _ = desk
    base = f"/redazione/api/politici/{politician_id}/blocchi/biography"
    saved = client.post(base, headers=ANNA, json=_biography(politician_id)).json()
    assert client.post(f"/redazione/api/coda/biography/{saved['id']}/rifiuta", headers=BRUNO, json={"note": "Manca la fonte del 1970."}).status_code == 200
    rejected = client.get("/redazione/api/panoramica", headers=ANNA).json()["my_rejected"]
    assert [row["note"] for row in rejected] == ["Manca la fonte del 1970."]
    assert rejected[0]["politician_id"] == politician_id
    assert client.get("/redazione/api/panoramica", headers=BRUNO).json()["my_rejected"] == []
    client.post(base, headers=ANNA, json=_biography(politician_id))
    assert client.get("/redazione/api/panoramica", headers=ANNA).json()["my_rejected"] == []
