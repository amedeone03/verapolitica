from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from scripts.prepare_demo import DEMO_ADMIN_KEY, prepare_demo


def demo_client(tmp_path):
    summary = prepare_demo(workspace_root=tmp_path / "workspace")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{summary.database_path}",
            raw_storage_path=summary.raw_storage_path,
            admin_api_key=DEMO_ADMIN_KEY,
            admin_reviewer_identity="demo-presenter",
        )
    )
    return TestClient(app)


def test_demo_ui_shell_and_rendering_assets_are_served(tmp_path):
    with demo_client(tmp_path) as client:
        page = client.get("/demo/")
        styles = client.get("/demo/styles.css")
        script = client.get("/demo/app.js")

    assert page.status_code == 200
    assert "VeraPolitica Demo" in page.text
    assert "Published profile" in page.text
    assert "Pending proposal" in page.text
    assert "Start review" in page.text
    assert "Approve &amp; publish" in page.text
    assert "Identity resolution" in page.text
    assert "Create new politician" in page.text
    assert styles.status_code == 200
    assert ".workflow-panel" in styles.text
    assert script.status_code == 200
    assert "renderPublishedProfile" in script.text
    assert "renderDraft" in script.text
    assert "/start-review" in script.text
    assert "/approve" in script.text
    assert "renderIdentityCase" in script.text
    assert "/admin/identity-resolution" in script.text


def test_demo_ui_api_flow_moves_pending_profile_to_public(tmp_path):
    headers = {"Authorization": f"Bearer {DEMO_ADMIN_KEY}"}
    with demo_client(tmp_path) as client:
        published = client.get("/politicians/1")
        draft = client.get("/admin/drafts/2", headers=headers)
        identity_case = client.get("/admin/identity-resolution/1", headers=headers)
        before = client.get("/politicians/2")
        started = client.post("/admin/drafts/2/start-review", headers=headers)
        approved = client.post(
            "/admin/drafts/2/approve",
            headers=headers,
            json={"note": "Official evidence verified during demo"},
        )
        after = client.get("/politicians/2")

    assert published.status_code == 200
    assert published.json()["given_name"] == "Anna"
    assert draft.status_code == 200
    assert draft.json()["status"] == "pending"
    assert len(draft.json()["evidence"]) == 14
    assert identity_case.status_code == 200
    assert identity_case.json()["candidate_display_name"] == "Carlo Verdi"
    assert before.status_code == 404
    assert started.status_code == 200
    assert started.json()["final_draft_status"] == "in_review"
    assert approved.status_code == 200
    assert approved.json()["final_draft_status"] == "approved"
    assert after.status_code == 200
    assert after.json()["given_name"] == "Luca"
    assert after.json()["citation_count"] == 14
    assert len(after.json()["citations"]) == 14
