from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from scripts.prepare_demo import DemoSafetyError
from scripts.reconcile_meloni_showcase import (
    BLOCKED_SOURCE,
    NEEDS_MANUAL_REVIEW,
    SHOWCASE_EXTRAS,
    main as reconcile_main,
    reconcile_meloni_showcase,
)


UNIFIED_DB = (
    Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
)
BLOCKED_TITLES = (
    "Abolire progressivamente le accise sui carburanti",
    "Rendere strutturale l’esenzione dal bollo auto",
)
EXPECTED = {
    "kept": 4,
    "partially_kept": 3,
    "in_progress": 2,
    "stalled": 1,
    "broken": 4,
}


def test_broken_still_requires_two_reviewers():
    assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
    assert len(DUAL_APPROVAL_VERDICTS) == 1


def test_operator_command_refuses_production(monkeypatch):
    monkeypatch.setattr(
        "scripts.reconcile_meloni_showcase.configured_environment",
        lambda: AppEnvironment.PRODUCTION,
    )
    with pytest.raises(DemoSafetyError, match="production"):
        reconcile_meloni_showcase(dry_run=True, allow_non_unified=True)
    assert reconcile_main(["--dry-run"]) == 1


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_second_apply_is_idempotent():
    first = reconcile_meloni_showcase(dry_run=False)
    second = reconcile_meloni_showcase(dry_run=False)
    assert first["public_pledge_count"] == 14
    assert second["created"] == 0
    assert second["approved"] == 0
    assert second["assessments_created"] == []
    assert len(second["assessments_reused"]) == 14
    assert second["distribution"] == first["distribution"]
    blocked = {row["ceo_number"]: row["action"] for row in second["audit"]}
    assert blocked[10] == BLOCKED_SOURCE
    assert blocked[16] == NEEDS_MANUAL_REVIEW


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_public_scorecard_ask_and_spiegami_use_active_showcase():
    with TestClient(
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
    ) as client:
        scorecard = client.get("/politicians/206/scorecard").json()
        public = client.get("/politicians/206").json()
        accise = client.get("/proposals/119")
        bollo = client.get("/proposals/124")
        autonomia = client.get("/proposals/106")
        rdc = next(
            item
            for item in scorecard["pledges"]
            if "Reddito di cittadinanza" in item["title"]
        )
        explanation = client.get(f"/proposals/{rdc['proposal_id']}/explanation").json()
        asked = client.post(
            "/ask",
            json={"question": "Quali promesse pubblicate ha Giorgia Meloni?"},
        ).json()

    assert scorecard["methodology_version"] == "pledge-score/v1"
    assert scorecard["tracked_pledges"] == 14
    assert Counter(item["verdict"] for item in scorecard["pledges"]) == Counter(EXPECTED)
    assert all(item["latest_assessment"] for item in scorecard["pledges"])
    blob = str(scorecard) + str(public) + str(asked) + str(explanation)
    assert "suggested_verdict" not in blob
    assert "reference-assessment-editor" not in blob
    assert "giorgia_meloni_v1" not in blob
    for title in BLOCKED_TITLES:
        assert title not in blob
    assert "autonomia differenziata" not in str(scorecard).casefold()
    assert accise.status_code == 404
    assert bollo.status_code == 404
    assert autonomia.status_code == 404
    assert explanation["verdict"] == "kept"
    assert explanation["sources"]
    assert explanation["sources"][0]["excerpt"]
    assert "gazzettaufficiale.it" in explanation["sources"][0]["url"]
    assert asked["intent"] in {"politician_pledges", "pledges_by_verdict"}
    assert all(item.get("verdict") != "not_yet_rated" for item in asked["results"])
    public_titles = {item["title"] for item in public["proposals"]}
    assert "Abolire e sostituire il Reddito di cittadinanza" in public_titles
    assert not any("autonomia differenziata" in title.casefold() for title in public_titles)
    assert SHOWCASE_EXTRAS
