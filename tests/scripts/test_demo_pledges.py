from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from scripts.prepare_demo import DEMO_ADMIN_KEY, prepare_demo


def test_demo_pledges_produce_a_public_scorecard(tmp_path):
    summary = prepare_demo(workspace_root=tmp_path / "workspace", include_pledges=True)
    app = create_app(
        Settings(
            database_url=f"sqlite:///{summary.database_path}",
            raw_storage_path=summary.raw_storage_path,
            admin_api_key=DEMO_ADMIN_KEY,
        )
    )
    headers = {"Authorization": f"Bearer {DEMO_ADMIN_KEY}"}
    with TestClient(app) as client:
        card = client.get(f"/politicians/{summary.published_politician_id}/scorecard").json()
        pending = client.get("/admin/pledges/assessment-drafts?status=pending", headers=headers).json()
        proposals = client.get("/proposals").json()

    assert card["tracked_pledges"] == 13
    assert card["excluded_vague_pledges"] == 1
    (stratum,) = card["strata"]
    assert stratum["role"] == "government_coalition"
    assert stratum["closed_pledges"] == 9
    assert stratum["rate"] == round(7 / 9, 4)
    assert {p["verdict"] for p in card["pledges"]} >= {"kept", "partially_kept", "broken", "stalled"}
    assert all("(demo" in p["title"] for p in card["pledges"])
    assert len(pending) == 1 and pending[0]["origin"] == "evidence_matcher"
    assert proposals["total"] == 14


def test_default_demo_keeps_its_original_shape(tmp_path):
    summary = prepare_demo(workspace_root=tmp_path / "workspace")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{summary.database_path}",
            raw_storage_path=summary.raw_storage_path,
        )
    )
    with TestClient(app) as client:
        card = client.get(f"/politicians/{summary.published_politician_id}/scorecard").json()
    assert card["tracked_pledges"] == 0
