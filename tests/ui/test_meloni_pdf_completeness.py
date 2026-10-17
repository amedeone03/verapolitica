import json
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app
from backend.app.services.reference_profile_audit import DEFAULT_FIXTURE


UNIFIED_DB = (
    Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
)
SCRIPT = Path("frontend/app/app.js")
BLOCKED_TITLES = (
    "Abolire progressivamente le accise sui carburanti",
    "Rendere strutturale l’esenzione dal bollo auto",
)
PROCEEDING_TITLES = (
    "Caso Almasri (2025)",
    "Naufragio di Cutro (2023)",
    "Accordo Italia–Albania sui migranti (2023–2026)",
    "Rapporti con il passato fascista e inchiesta su Gioventù Nazionale (2024)",
)
EXPECTED_VERDICTS = {
    "kept": 4,
    "partially_kept": 3,
    "in_progress": 2,
    "stalled": 1,
    "broken": 4,
}


def _unified_client():
    return TestClient(
        create_app(
            Settings(
                env=AppEnvironment.DEVELOPMENT,
                database_url=f"sqlite:///{UNIFIED_DB}",
                raw_storage_path=UNIFIED_DB.parent / "raw",
                admin_api_key="local-presentation-admin-key",
                trusted_hosts="localhost,127.0.0.1,testserver",
                enable_demo_ui=False,
            )
        )
    )


def test_frontend_does_not_hard_code_pdf_facts():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "export function currentParty" in script
    assert "item.party_or_group" in script.split("export function currentParty")[1].split(
        "export function primaryMandate"
    )[0]
    assert "explicitlyCurrent(item)" in script.split("export function currentParty")[1]
    assert "Giorgia Meloni è nata" not in script
    assert 'family_name === "Meloni"' not in script
    assert "15 gennaio 1977" not in script
    assert "Caso Almasri" not in script
    assert "Naufragio di Cutro" not in script
    assert "Gioventù Nazionale" not in script
    assert "Abolire progressivamente le accise" not in script
    assert "declaration_source_url" in script
    assert "assessment.source_url" in script
    assert "item.verifiable_statement" in script
    assert "item.position_statement" in script
    assert "item.outcome_summary" in script


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_public_meloni_profile_exposes_published_pdf_fields_only():
    fixture = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    with _unified_client() as client:
        person = client.get("/politicians/206").json()
        scorecard = client.get("/politicians/206/scorecard").json()
        accise = client.get("/proposals/119")
        bollo = client.get("/proposals/124")

    assert person["given_name"] == "Giorgia"
    assert person["family_name"] == "Meloni"
    assert person["birth_date"] == "1977-01-15"
    assert person["profile"]["birth_place"]["city"] == "Roma"
    mandate = next(
        item
        for item in person["profile"]["mandates"]
        if "presidente del consiglio" in str(item.get("mandate_type") or "").casefold()
        or "presidente del consiglio" in str(item.get("office") or "").casefold()
    )
    assert mandate["start_date"] == "2022-10-21"
    assert person["political_parties"] in ([], None) or person["political_parties"] == []
    fdi = next(
        item
        for item in person["career_entries"]
        if item["is_current"] and item.get("party_or_group") == "Fratelli d’Italia"
    )
    assert "Presidente nazionale" in fdi["role"]

    biography = person["biography"]["body"]
    assert "diplomata in lingue" in biography.casefold()
    assert "Fronte della Gioventù" in biography
    assert "ottobre 2022" in biography
    assert "22 ottobre 2022" not in biography
    bio_names = {source["name"] for source in person["biography"]["sources"]}
    assert any("Presidenza" in name for name in bio_names)
    assert any(source.get("url") for source in person["biography"]["sources"])

    roles = {item["role"] for item in person["career_entries"]}
    expected_roles = {item["role"] for item in fixture["career_entries"]}
    assert expected_roles <= roles
    assert not any("Presidente del Consiglio" in role for role in roles)
    assert all(item.get("sources") for item in person["career_entries"])

    topics = {item["topic"] for item in person["positions"]}
    assert topics == {item["topic"] for item in fixture["positions"]}
    for item in person["positions"]:
        assert item["position_statement"]
        assert item["verifiable_statement"]
        assert item["sources"]
        assert all(source.get("url") for source in item["sources"])

    assert person["proceedings"] == []
    public_blob = str(person) + str(scorecard)
    for title in PROCEEDING_TITLES + BLOCKED_TITLES:
        assert title not in public_blob
    assert "favoreggiamento" not in public_blob.casefold()
    assert "suggested_verdict" not in public_blob
    assert "reference-profile-operator" not in public_blob

    assert scorecard["tracked_pledges"] == 14
    assert Counter(item["verdict"] for item in scorecard["pledges"]) == Counter(EXPECTED_VERDICTS)
    for pledge in scorecard["pledges"]:
        assert pledge["introduced_at"]
        assert pledge["declaration_source_url"] or pledge["declaration_source_name"]
        assert pledge["latest_assessment"]
        assert pledge["latest_assessment"]["rationale"]
        assert pledge["latest_assessment"]["source_url"]
    assert accise.status_code == 404
    assert bollo.status_code == 404
