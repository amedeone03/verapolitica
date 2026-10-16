from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models.politician_profile import ProfileContentKind
from scripts.prepare_reference_profile import prepare_reference_profile
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


ADMIN = {"Authorization": "Bearer profile-admin"}


def test_public_api_hides_unpublished_profile_content(session_factory, tmp_path):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="profile-admin",
        admin_reviewer_identity="desk-one",
    )
    with TestClient(create_app(settings)) as client:
        payload = client.get(f"/politicians/{ids['politician_id']}").json()
        assert payload["biography"] is None
        assert payload["positions"] == []
        assert payload["proceedings"] == []
        assert payload["career_entries"] == []
        assert "reviewed_by" not in payload
        assert "review_note" not in payload
        pending = client.get(
            "/admin/profile-content?status=pending", headers=ADMIN
        ).json()
        assert pending["total"] >= 4
        proceeding = next(
            item for item in pending["items"] if item["kind"] == "proceeding"
        )
        assert proceeding["sources_incomplete"] is True
        approved = client.post(
            f"/admin/profile-content/{ProfileContentKind.PROCEEDING.value}/{proceeding['id']}/approve",
            headers=ADMIN,
            json={"note": "fonte ancora incompleta, pubblicazione di prova"},
        )
        assert approved.status_code == 200, approved.text
        public = client.get(f"/politicians/{ids['politician_id']}").json()
        assert public["biography"] is None
        assert len(public["proceedings"]) == 1
        assert public["proceedings"][0]["proceeding_types"]
        assert "reviewed_by" not in public["proceedings"][0]
        scorecard = client.get(f"/politicians/{ids['politician_id']}/scorecard").json()
        assert scorecard["methodology_version"] == "pledge-score/v1"
        assert scorecard["tracked_pledges"] == 1
        assert scorecard["pledges"][0]["verdict"] == "in_progress"
        assert scorecard["pledges"][0]["latest_assessment"]["id"] == assessment_id
        strata = scorecard["strata"][0]
        assert strata["rate"] is None
        assert strata["rate_withheld_reason"] == "no_closed_pledges"
