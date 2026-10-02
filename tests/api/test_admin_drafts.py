from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    Evidence,
    EvidenceExtractionMethod,
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
    Review,
    ReviewDecision,
    Source,
)
from backend.app.schemas import (
    ChangeType,
    DiffStatus,
    FieldChange,
    PoliticalMandate,
    PoliticianVersionProfile,
    ProfileDiff,
    ReviewDecisionResult,
)
from backend.app.services import normalize_person_name


@dataclass
class APIContext:
    client: TestClient
    session_factory: object
    headers: dict[str, str]
    update_draft_id: int
    initial_draft_id: int
    rejected_draft_id: int
    update_politician_id: int
    initial_politician_id: int
    baseline_version_id: int


def profile(name: str, *, profession: str | None) -> PoliticianVersionProfile:
    return PoliticianVersionProfile(
        given_name=name,
        family_name="Rossi",
        birth_date=date(1970, 1, 2),
        birth_place=None,
        gender=None,
        profession=profession,
        image_url=None,
        official_homepage_url=None,
        mandates=(
            PoliticalMandate(
                institution="Senato della Repubblica",
                office="senator",
                legislature="19",
                mandate_type="elettivo",
                start_date=date(2022, 10, 13),
            ),
        ),
    )


def add_politician(session, name: str) -> Politician:
    politician = Politician(
        canonical_given_name=name,
        canonical_family_name="Rossi",
        normalized_name=normalize_person_name(name, "Rossi"),
        birth_date=date(1970, 1, 2),
    )
    session.add(politician)
    session.flush()
    return politician


def diff_data(
    status: DiffStatus,
    proposed: PoliticianVersionProfile,
    *,
    field_path: str,
    old_value,
    new_value,
) -> dict:
    return ProfileDiff(
        status=status,
        proposed_profile=proposed,
        changes=(
            FieldChange(
                field_path=field_path,
                change_type=(
                    ChangeType.ADDED if old_value is None else ChangeType.CHANGED
                ),
                old_value=old_value,
                new_value=new_value,
            ),
        ),
    ).model_dump(mode="json")


@pytest.fixture
def api_context(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'admin-api.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        admin_reviewer_identity="api-editor",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
    with factory() as session:
        source = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=now,
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/admin-api.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add(document)
        session.flush()

        update_politician = add_politician(session, "Maria")
        baseline_profile = profile("Maria", profession="Avvocata")
        baseline = PoliticianVersion(
            politician_id=update_politician.id,
            version_number=1,
            profile_schema_version=1,
            profile_data=baseline_profile.model_dump(mode="json"),
            published_at=now - timedelta(days=1),
        )
        session.add(baseline)
        session.flush()
        update_politician.current_version_id = baseline.id
        update_profile = profile("Maria", profession="Magistrata")
        update_draft = ProfileDraft(
            politician_id=update_politician.id,
            baseline_version_id=baseline.id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.UPDATE,
            status=ProfileDraftStatus.PENDING,
            proposed_profile_data=update_profile.model_dump(mode="json"),
            diff_data=diff_data(
                DiffStatus.UPDATE,
                update_profile,
                field_path="profession",
                old_value="Avvocata",
                new_value="Magistrata",
            ),
            created_at=now,
            updated_at=now,
        )
        session.add(update_draft)
        session.flush()
        session.add(
            Evidence(
                draft_id=update_draft.id,
                field_path="profession",
                raw_document_id=document.id,
                source_url=document.source_url,
                source_record_identifier="https://dati.senato.it/senatore/100",
                source_field_name="profession",
                source_value="Magistrata",
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
                created_at=now,
            )
        )

        initial_politician = add_politician(session, "Luca")
        initial_profile = profile("Luca", profession=None)
        initial_draft = ProfileDraft(
            politician_id=initial_politician.id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.INITIAL,
            status=ProfileDraftStatus.PENDING,
            proposed_profile_data=initial_profile.model_dump(mode="json"),
            diff_data=diff_data(
                DiffStatus.INITIAL,
                initial_profile,
                field_path="given_name",
                old_value=None,
                new_value="Luca",
            ),
            created_at=now + timedelta(minutes=1),
            updated_at=now + timedelta(minutes=1),
        )
        session.add(initial_draft)
        session.flush()
        session.add(
            Evidence(
                draft_id=initial_draft.id,
                field_path="given_name",
                raw_document_id=document.id,
                source_url=document.source_url,
                source_record_identifier="https://dati.senato.it/senatore/101",
                source_field_name="firstName",
                source_value="Luca",
                extraction_method=EvidenceExtractionMethod.DETERMINISTIC,
                created_at=now,
            )
        )

        rejected_politician = add_politician(session, "Anna")
        rejected_profile = profile("Anna", profession=None)
        rejected_draft = ProfileDraft(
            politician_id=rejected_politician.id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.INITIAL,
            status=ProfileDraftStatus.REJECTED,
            proposed_profile_data=rejected_profile.model_dump(mode="json"),
            diff_data=diff_data(
                DiffStatus.INITIAL,
                rejected_profile,
                field_path="given_name",
                old_value=None,
                new_value="Anna",
            ),
            created_at=now + timedelta(minutes=2),
            updated_at=now + timedelta(minutes=2),
        )
        session.add(rejected_draft)
        session.flush()
        session.add(
            Review(
                draft_id=rejected_draft.id,
                reviewer="seed-editor",
                decision=ReviewDecision.REJECTED,
                note="Seed rejection",
                created_at=now + timedelta(minutes=3),
            )
        )
        session.commit()
        identifiers = (
            update_draft.id,
            initial_draft.id,
            rejected_draft.id,
            update_politician.id,
            initial_politician.id,
            baseline.id,
        )

    app = create_app(settings)
    with TestClient(app) as client:
        yield APIContext(
            client=client,
            session_factory=factory,
            headers={"Authorization": "Bearer test-admin-secret"},
            update_draft_id=identifiers[0],
            initial_draft_id=identifiers[1],
            rejected_draft_id=identifiers[2],
            update_politician_id=identifiers[3],
            initial_politician_id=identifiers[4],
            baseline_version_id=identifiers[5],
        )
    engine.dispose()


def test_health_endpoint_boots_without_admin_auth(api_context):
    response = api_context.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_routes_reject_missing_or_invalid_credentials(api_context):
    missing = api_context.client.get("/admin/drafts")
    invalid = api_context.client.get(
        "/admin/drafts",
        headers={"Authorization": "Bearer wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"


def test_authenticated_list_is_active_first_and_paginated(api_context):
    response = api_context.client.get(
        "/admin/drafts?offset=0&limit=2",
        headers=api_context.headers,
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 3
    assert payload["offset"] == 0
    assert payload["limit"] == 2
    assert [item["status"] for item in payload["items"]] == ["pending", "pending"]
    assert payload["items"][0]["id"] == api_context.initial_draft_id
    assert payload["items"][1]["evidence_count"] == 1


def test_list_filters_by_status_and_source(api_context):
    response = api_context.client.get(
        "/admin/drafts?status=rejected&source_key=senato-repubblica",
        headers=api_context.headers,
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == api_context.rejected_draft_id
    assert payload["items"][0]["final_review_decision"] == "rejected"


def test_draft_detail_contains_diff_evidence_and_version_context(api_context):
    response = api_context.client.get(
        f"/admin/drafts/{api_context.update_draft_id}",
        headers=api_context.headers,
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["diff"]["changes"][0]["field_path"] == "profession"
    assert payload["evidence"][0]["source_field_name"] == "profession"
    assert payload["evidence"][0]["source_value"] == "Magistrata"
    assert payload["source_document"]["source_key"] == "senato-repubblica"
    assert payload["source_document"]["raw_sha256"] == "a" * 64
    assert payload["baseline_version"]["id"] == api_context.baseline_version_id
    assert payload["current_version"]["id"] == api_context.baseline_version_id


def test_missing_draft_returns_404_error_envelope(api_context):
    response = api_context.client.get(
        "/admin/drafts/9999",
        headers=api_context.headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "draft_not_found"


def test_start_review_succeeds_then_invalid_repeat_is_409(api_context):
    path = f"/admin/drafts/{api_context.initial_draft_id}/start-review"

    first = api_context.client.post(path, headers=api_context.headers)
    second = api_context.client.post(path, headers=api_context.headers)

    assert first.status_code == 200
    assert first.json()["final_draft_status"] == "in_review"
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "draft_not_reviewable"
    with api_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1


def test_approve_uses_authenticated_identity_and_publish_service(api_context):
    response = api_context.client.post(
        f"/admin/drafts/{api_context.update_draft_id}/approve",
        headers=api_context.headers,
        json={"note": "Verified"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["decision"] == "approved"
    assert payload["version_number"] == 2
    assert payload["created_version_id"] == payload["current_version_id"]
    with api_context.session_factory() as session:
        review = session.get(Review, payload["review_id"])
        assert review is not None and review.reviewer == "api-editor"
        assert review.note == "Verified"
        politician = session.get(Politician, api_context.update_politician_id)
        assert politician.current_version_id == payload["created_version_id"]


def test_request_body_cannot_spoof_reviewer_identity(api_context):
    response = api_context.client.post(
        f"/admin/drafts/{api_context.initial_draft_id}/approve",
        headers=api_context.headers,
        json={"reviewer": "spoofed-editor"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_stale_approval_returns_409_without_writes(api_context):
    with api_context.session_factory() as session:
        newer = PoliticianVersion(
            politician_id=api_context.update_politician_id,
            version_number=2,
            profile_schema_version=1,
            profile_data=profile("Maria", profession="Docente").model_dump(mode="json"),
            published_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
        )
        session.add(newer)
        session.flush()
        politician = session.get(Politician, api_context.update_politician_id)
        politician.current_version_id = newer.id
        session.commit()

    response = api_context.client.post(
        f"/admin/drafts/{api_context.update_draft_id}/approve",
        headers=api_context.headers,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stale_draft"
    with api_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.get(ProfileDraft, api_context.update_draft_id).status is ProfileDraftStatus.PENDING


def test_repeated_approval_returns_409_without_duplicate_records(api_context):
    path = f"/admin/drafts/{api_context.initial_draft_id}/approve"
    first = api_context.client.post(path, headers=api_context.headers, json={})
    second = api_context.client.post(path, headers=api_context.headers, json={})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "draft_not_reviewable"
    with api_context.session_factory() as session:
        versions = session.scalar(
            select(func.count())
            .select_from(PoliticianVersion)
            .where(PoliticianVersion.politician_id == api_context.initial_politician_id)
        )
        reviews = session.scalar(
            select(func.count())
            .select_from(Review)
            .where(Review.draft_id == api_context.initial_draft_id)
        )
        assert (versions, reviews) == (1, 1)


def test_reject_creates_review_but_no_version(api_context):
    before_versions = None
    with api_context.session_factory() as session:
        before_versions = session.scalar(
            select(func.count()).select_from(PoliticianVersion)
        )

    response = api_context.client.post(
        f"/admin/drafts/{api_context.initial_draft_id}/reject",
        headers=api_context.headers,
        json={"note": "Needs clarification"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["decision"] == "rejected"
    assert payload["created_version_id"] is None
    assert payload["version_number"] is None
    with api_context.session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(PoliticianVersion))
            == before_versions
        )
        review = session.get(Review, payload["review_id"])
        assert review is not None and review.reviewer == "api-editor"


def test_reject_terminal_draft_returns_409(api_context):
    response = api_context.client.post(
        f"/admin/drafts/{api_context.rejected_draft_id}/reject",
        headers=api_context.headers,
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "draft_not_reviewable"


def test_invalid_query_and_body_return_422(api_context):
    invalid_page = api_context.client.get(
        "/admin/drafts?limit=0",
        headers=api_context.headers,
    )
    invalid_body = api_context.client.post(
        f"/admin/drafts/{api_context.initial_draft_id}/reject",
        headers=api_context.headers,
        json={"note": ["not", "a", "string"]},
    )

    assert invalid_page.status_code == 422
    assert invalid_body.status_code == 422
    assert invalid_page.json()["error"]["code"] == "validation_error"


def test_approve_route_delegates_to_publish_service(
    api_context, monkeypatch
):
    called = {}

    def fake_approve(self, draft_id, *, reviewer, note=None):
        called.update(draft_id=draft_id, reviewer=reviewer, note=note)
        return ReviewDecisionResult(
            review_id=88,
            decision=ReviewDecision.APPROVED,
            draft_id=draft_id,
            politician_id=api_context.update_politician_id,
            created_version_id=99,
            version_number=2,
            current_version_id=99,
            final_draft_status=ProfileDraftStatus.APPROVED,
        )

    monkeypatch.setattr(
        "backend.app.api.admin.drafts.PublishService.approve",
        fake_approve,
    )
    response = api_context.client.post(
        f"/admin/drafts/{api_context.update_draft_id}/approve",
        headers=api_context.headers,
        json={"note": "Delegated"},
    )

    assert response.status_code == 200
    assert called == {
        "draft_id": api_context.update_draft_id,
        "reviewer": "api-editor",
        "note": "Delegated",
    }
