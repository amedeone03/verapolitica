from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models.politician_profile import ProfileContentKind, ProfileContentStatus
from backend.app.schemas.politician_profile import SourceCompleteness
from backend.app.scoring.types import DUAL_APPROVAL_VERDICTS, FulfillmentVerdict
from backend.app.services.reference_profile_audit import CEO_REFERENCE_WARNING, EDITORIAL_PREVIEW_BANNER
from scripts.prepare_reference_profile import prepare_reference_profile
from tests.scripts.test_prepare_reference_profile import (
    _classify_and_assess_autonomia,
    _seed_meloni,
)


ADMIN = {"Authorization": "Bearer profile-admin"}
PUBLIC_LEAKS = (
    "reviewed_by",
    "review_note",
    "ceo_reference_warning",
    "reference_origin",
    "source_completeness",
    CEO_REFERENCE_WARNING,
    "reference-profile-operator",
    "ANTEPRIMA EDITORIALE",
    "desk-one",
)


def _client(tmp_path, *, demo_ui: bool = False):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="profile-admin",
        admin_reviewer_identity="desk-one",
        enable_demo_ui=demo_ui,
    )


def _prepare(session_factory):
    ids = _seed_meloni(session_factory)
    assessment_id = _classify_and_assess_autonomia(session_factory, ids)
    prepare_reference_profile(
        session_factory=session_factory, dry_run=False, allow_non_unified=True
    )
    return ids, assessment_id


def test_public_api_hides_unpublished_profile_content(session_factory, tmp_path):
    ids, assessment_id = _prepare(session_factory)
    settings = _client(tmp_path)
    with TestClient(create_app(settings)) as client:
        payload = client.get(f"/politicians/{ids['politician_id']}").json()
        blob = str(payload)
        assert payload["biography"] is None
        assert payload["positions"] == []
        assert payload["proceedings"] == []
        assert payload["career_entries"] == []
        for leak in PUBLIC_LEAKS:
            assert leak not in blob
        pending = client.get(
            "/admin/profile-content?status=pending", headers=ADMIN
        ).json()
        assert pending["total"] >= 4
        proceeding = next(
            item for item in pending["items"] if item["kind"] == "proceeding"
        )
        assert proceeding["sources_incomplete"] is True
        assert proceeding["source_completeness"] == SourceCompleteness.MISSING_SOURCE_URL.value
        assert proceeding["proceeding_nature"]
        assert proceeding["ceo_reference_warning"] == CEO_REFERENCE_WARNING
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
        public_blob = str(public)
        for leak in PUBLIC_LEAKS:
            assert leak not in public_blob
        scorecard = client.get(f"/politicians/{ids['politician_id']}/scorecard").json()
        assert scorecard["methodology_version"] == "pledge-score/v1"
        assert scorecard["tracked_pledges"] == 1
        assert scorecard["pledges"][0]["verdict"] == "in_progress"
        assert scorecard["pledges"][0]["latest_assessment"]["id"] == assessment_id
        strata = scorecard["strata"][0]
        assert strata["rate"] is None
        assert strata["rate_withheld_reason"] == "no_closed_pledges"


def test_kind_approval_publication_boundaries(session_factory, tmp_path):
    ids, _assessment_id = _prepare(session_factory)
    settings = _client(tmp_path)
    politician_id = ids["politician_id"]
    with TestClient(create_app(settings)) as client:
        pending = client.get(
            f"/admin/profile-content?status=pending&politician_id={politician_id}&limit=100",
            headers=ADMIN,
        ).json()["items"]
        biography = next(item for item in pending if item["kind"] == "biography")
        career = next(item for item in pending if item["kind"] == "career_entry")
        position = next(item for item in pending if item["kind"] == "position")
        proceeding = next(
            item
            for item in pending
            if item["kind"] == "proceeding" and item["identity_key"] != "caso-almasri-2025"
        )
        reject_target = next(
            item
            for item in pending
            if item["kind"] == "proceeding" and item["identity_key"] == "caso-almasri-2025"
        )
        assert biography["source_completeness"] == SourceCompleteness.READY_FOR_EDITORIAL_REVIEW.value
        assert biography["incomplete_secondary_sources"]
        assert position["verifiable_statement"]
        assert position["statement_date"]
        for item, kind in (
            (biography, ProfileContentKind.BIOGRAPHY),
            (career, ProfileContentKind.CAREER_ENTRY),
            (position, ProfileContentKind.POSITION),
            (proceeding, ProfileContentKind.PROCEEDING),
        ):
            response = client.post(
                f"/admin/profile-content/{kind.value}/{item['id']}/approve",
                headers=ADMIN,
                json={"note": "isolated publication boundary"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == ProfileContentStatus.PUBLISHED.value
        rejected = client.post(
            f"/admin/profile-content/{ProfileContentKind.PROCEEDING.value}/{reject_target['id']}/reject",
            headers=ADMIN,
            json={"note": "URL mancante"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == ProfileContentStatus.REJECTED.value
        public = client.get(f"/politicians/{politician_id}").json()
        assert public["biography"]["body"]
        assert public["career_entries"]
        assert public["positions"]
        titles = {item["title"] for item in public["proceedings"]}
        assert reject_target["title"] not in titles
        assert proceeding["title"] in titles
        blob = str(public)
        assert CEO_REFERENCE_WARNING not in blob
        assert "reference-profile-operator" not in blob


def test_editorial_preview_is_bearer_protected_and_does_not_publish(
    session_factory, tmp_path
):
    ids, _assessment_id = _prepare(session_factory)
    settings = _client(tmp_path, demo_ui=True)
    politician_id = ids["politician_id"]
    with TestClient(create_app(settings)) as client:
        missing = client.get(f"/admin/politicians/{politician_id}/editorial-preview")
        assert missing.status_code == 401
        preview = client.get(
            f"/admin/politicians/{politician_id}/editorial-preview", headers=ADMIN
        )
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        assert payload["banner"] == EDITORIAL_PREVIEW_BANNER
        assert payload["publication_unchanged"] is True
        assert payload["biography"]["status"] == "pending"
        assert payload["pending_counts"]["proceedings"] == 4
        public = client.get(f"/politicians/{politician_id}").json()
        assert public["biography"] is None
        assert public["proceedings"] == []
        desk = client.get("/demo/profile-review")
        assert desk.status_code == 200
        assert "Load pending" in desk.text
        assert CEO_REFERENCE_WARNING not in desk.text
        assert "Caso Almasri" not in desk.text
        assert "profile-review.js" in desk.text
        js = client.get("/demo/profile-review.js")
        assert js.status_code == 200
        public_app = client.get("/app/")
        assert public_app.status_code == 200
        assert "editorial-preview" not in public_app.text


def test_attach_source_url_is_admin_only_and_does_not_publish(session_factory, tmp_path):
    ids, _assessment_id = _prepare(session_factory)
    settings = _client(tmp_path)
    politician_id = ids["politician_id"]
    with TestClient(create_app(settings)) as client:
        pending = client.get(
            f"/admin/profile-content?status=pending&politician_id={politician_id}&kind=proceeding",
            headers=ADMIN,
        ).json()["items"]
        proceeding = next(
            item for item in pending if item["identity_key"] == "caso-almasri-2025"
        )
        source_id = proceeding["source_ids"][0]
        denied = client.post(
            f"/admin/profile-content/proceeding/{proceeding['id']}/sources/{source_id}",
            json={"url": "https://www.ansa.it/sito/notizie/example.html"},
        )
        assert denied.status_code == 401
        invalid = client.post(
            f"/admin/profile-content/proceeding/{proceeding['id']}/sources/{source_id}",
            headers=ADMIN,
            json={"url": "not-a-url"},
        )
        assert invalid.status_code == 422
        attached = client.post(
            f"/admin/profile-content/proceeding/{proceeding['id']}/sources/{source_id}",
            headers=ADMIN,
            json={"url": "https://www.ansa.it/sito/notizie/example.html"},
        )
        assert attached.status_code == 200, attached.text
        payload = attached.json()
        assert payload["status"] == ProfileContentStatus.PENDING.value
        assert any(item.get("url") for item in payload["sources"])
        public = client.get(f"/politicians/{politician_id}").json()
        assert public["proceedings"] == []


def test_pending_pledge_drafts_are_not_public_and_ask_is_unchanged(
    session_factory, tmp_path
):
    ids, assessment_id = _prepare(session_factory)
    settings = _client(tmp_path)
    with TestClient(create_app(settings)) as client:
        person = client.get(f"/politicians/{ids['politician_id']}").json()
        titles = {item["title"] for item in person.get("proposals") or []}
        assert "Abolire e sostituire il Reddito di cittadinanza" not in titles
        scorecard = client.get(f"/politicians/{ids['politician_id']}/scorecard").json()
        assert scorecard["pledges"][0]["latest_assessment"]["id"] == assessment_id
        explanation = client.get(
            f"/proposals/{ids['autonomia_id']}/explanation"
        )
        assert explanation.status_code == 200
        spec = client.get("/openapi.json").json()["paths"]
        assert "/ask" in spec
        assert any(path.endswith("/explanation") for path in spec)
        assert FulfillmentVerdict.BROKEN in DUAL_APPROVAL_VERDICTS
        assert len(DUAL_APPROVAL_VERDICTS) == 1
