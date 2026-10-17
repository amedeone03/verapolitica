from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.main import create_app


UNIFIED_DB = (
    Path(__file__).resolve().parents[2] / "data" / "unified_demo" / "verapolitica.db"
)

PUBLIC_VERDICTS = (
    "kept",
    "partially_kept",
    "in_progress",
    "stalled",
    "broken",
    "not_yet_rated",
)

PUBLIC_LABELS = {
    "kept": "Mantenuta",
    "partially_kept": "Mantenuta parzialmente",
    "in_progress": "In corso",
    "stalled": "Iter bloccato",
    "broken": "Non mantenuta",
    "not_yet_rated": "Non ancora valutata",
}

BLOCKED_DRAFT_TITLES = (
    "Abolire progressivamente le accise sui carburanti",
    "Rendere strutturale l’esenzione dal bollo auto",
)


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


def test_frontend_reuses_central_public_status_mapping():
    script = Path("frontend/app/app.js").read_text(encoding="utf-8")
    styles = Path("frontend/app/styles.css").read_text(encoding="utf-8")

    assert "const VERDICTS = {" in script
    for value, label in PUBLIC_LABELS.items():
        assert f'{value}: {{ label: "{label}"' in script
    assert "countPledgeVerdicts(pledges)" in script
    assert "if (pledge.verdict in VERDICTS)" in script
    assert "renderPledgeStatusSummary(counts, counts.all)" in script
    assert "renderPledgeDistribution(counts, counts.all)" in script
    assert "renderCompositionBar(composition, { compact: true })" in script
    assert "Nessuna promessa pubblicata con questo stato." in script
    assert "Distribuzione degli stati pubblicati. Non è un punteggio di performance." in script
    assert 'empty.hidden = visible > 0' in script
    assert 'role="group"' in script
    assert "aria-pressed" in script
    assert "aria-live=\"polite\"" in script
    assert "PLEDGE_FILTER_LABELS" in script
    assert 'kept: "Mantenute"' in script
    assert 'broken: "Non mantenute"' in script
    assert 'not_yet_rated: "Non ancora valutate"' in script
    assert ".pledge-status-summary" in styles
    assert ".pledge-summary-grid" in styles
    assert ".pledge-distribution" in styles
    assert ".pledge-item .verdict-chip" in styles
    assert ".filter-pill.is-zero" in styles
    assert "border-left: 3px solid var(--tone" in styles


@pytest.mark.skipif(not UNIFIED_DB.exists(), reason="unified demo database is not present")
def test_meloni_summary_counts_match_published_scorecard_only():
    with _unified_client() as client:
        scorecard = client.get("/politicians/206/scorecard").json()
        script = client.get("/app/app.js").text
        accise = client.get("/proposals/119")
        bollo = client.get("/proposals/124")

    assert scorecard["methodology_version"] == "pledge-score/v1"
    assert scorecard["tracked_pledges"] == 14
    assert len(scorecard["pledges"]) == 14
    verdicts = Counter(item["verdict"] for item in scorecard["pledges"])
    assert verdicts == Counter(
        {
            "kept": 4,
            "partially_kept": 3,
            "in_progress": 2,
            "stalled": 1,
            "broken": 4,
        }
    )
    assert set(verdicts) <= set(PUBLIC_VERDICTS)
    blob = str(scorecard)
    for title in BLOCKED_DRAFT_TITLES:
        assert title not in blob
    assert "autonomia differenziata" not in blob.casefold()
    assert accise.status_code == 404
    assert bollo.status_code == 404
    assert "countPledgeVerdicts(pledges)" in script
    assert "scorecard.pledges" in script
    assert "pending" not in {item.get("verdict") for item in scorecard["pledges"]}
    assert all(item.get("latest_assessment") for item in scorecard["pledges"])
    assert verdicts.get("not_yet_rated", 0) == 0
