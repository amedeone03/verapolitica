from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    IdentityResolutionCase,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    CandidateIdentity,
    CandidateProfile,
    CandidateProfileData,
    CandidateProvenance,
    NewMatchReason,
    NewResult,
    PoliticalMandate,
    SourceDocumentProvenance,
    SourceIdentifier,
)
from backend.app.services import IdentityResolutionService, normalize_person_name


@dataclass
class IdentityAPIContext:
    client: TestClient
    session_factory: object
    headers: dict[str, str]
    case_ids: tuple[int, int, int]
    existing_politician_id: int


def make_candidate(document: RawDocument, sequence: int) -> CandidateProfile:
    profile_url = f"https://www.governo.it/it/governo/example/antonio-{sequence}"
    return CandidateProfile(
        identity=CandidateIdentity(
            display_name="Antonio Example",
            given_name="Antonio",
            family_name="Example",
            source_identifiers=(
                SourceIdentifier(
                    authority="governo-italiano",
                    value=f"https://www.governo.it/it/node/{9100 + sequence}",
                ),
            ),
        ),
        profile=CandidateProfileData(
            official_homepage_url=profile_url,
            mandates=(
                PoliticalMandate(
                    institution="Governo Italiano",
                    office="Sottosegretario",
                    legislature="Governo Meloni",
                    mandate_type="Sottosegretario di Stato",
                    start_date=date(2022, 10, 31),
                ),
            ),
        ),
        provenance=CandidateProvenance(
            document=SourceDocumentProvenance(
                source_key="governo-italiano",
                raw_document_id=document.id,
                source_url=document.source_url,
                retrieved_at=document.retrieved_at,
                raw_sha256=document.raw_sha256,
                normalized_sha256=document.normalized_sha256,
                collector_version=document.collector_version,
                parser_version=document.parser_version,
            ),
            fields=(),
        ),
    )


@pytest.fixture
def identity_api_context(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'identity-admin.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="identity-admin-secret",
        admin_reviewer_identity="trusted-identity-editor",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            storage_key="governo/admin-cases.json",
            raw_sha256="c" * 64,
            normalized_sha256="d" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="governo_collector_v1",
            parser_version="governo_parser_v1",
        )
        session.add(document)
        politician = Politician(
            canonical_given_name="Antonio",
            canonical_family_name="Example",
            normalized_name=normalize_person_name("Antonio", "Example"),
            birth_date=date(1970, 1, 1),
        )
        session.add(politician)
        session.commit()
        existing_id = politician.id

    service = IdentityResolutionService(factory)
    case_ids = tuple(
        service.create_or_reuse_case(
            make_candidate(document, sequence),
            NewResult(reason=NewMatchReason.INSUFFICIENT_FALLBACK_IDENTITY),
        ).case_id
        for sequence in range(1, 4)
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield IdentityAPIContext(
            client=client,
            session_factory=factory,
            headers={"Authorization": "Bearer identity-admin-secret"},
            case_ids=case_ids,
            existing_politician_id=existing_id,
        )
    engine.dispose()


def test_identity_resolution_routes_are_admin_only(identity_api_context):
    missing = identity_api_context.client.get("/admin/identity-resolution")
    invalid = identity_api_context.client.get(
        "/admin/identity-resolution",
        headers={"Authorization": "Bearer wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_list_and_detail_expose_snapshot_source_and_possible_matches(
    identity_api_context,
):
    listing = identity_api_context.client.get(
        "/admin/identity-resolution?status=pending&source_key=governo-italiano",
        headers=identity_api_context.headers,
    )
    detail = identity_api_context.client.get(
        f"/admin/identity-resolution/{identity_api_context.case_ids[0]}",
        headers=identity_api_context.headers,
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 3
    assert listing.json()["items"][0]["source"]["key"] == "governo-italiano"
    payload = detail.json()
    assert detail.status_code == 200
    assert payload["candidate_display_name"] == "Antonio Example"
    assert payload["candidate_snapshot"]["identity"]["birth_date"] is None
    assert payload["matching_result"]["reason"] == (
        "insufficient_fallback_identity"
    )
    assert payload["official_source_url"].startswith("https://www.governo.it/")
    assert payload["possible_matches"][0]["politician"]["id"] == (
        identity_api_context.existing_politician_id
    )
    assert payload["possible_matches"][0]["signals"] == [
        "normalized_full_name"
    ]


def test_resolve_existing_uses_trusted_reviewer_and_terminal_repeat_is_409(
    identity_api_context,
):
    case_id = identity_api_context.case_ids[0]
    spoof = identity_api_context.client.post(
        f"/admin/identity-resolution/{case_id}/resolve-existing",
        headers=identity_api_context.headers,
        json={
            "politician_id": identity_api_context.existing_politician_id,
            "reviewer_identity": "spoofed",
        },
    )
    resolved = identity_api_context.client.post(
        f"/admin/identity-resolution/{case_id}/resolve-existing",
        headers=identity_api_context.headers,
        json={
            "politician_id": identity_api_context.existing_politician_id,
            "note": "Official profiles inspected",
        },
    )
    repeated = identity_api_context.client.post(
        f"/admin/identity-resolution/{case_id}/ignore",
        headers=identity_api_context.headers,
        json={"note": "too late"},
    )

    assert spoof.status_code == 422
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved_existing"
    assert resolved.json()["reviewer_identity"] == "trusted-identity-editor"
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "identity_resolution_conflict"
    with identity_api_context.session_factory() as session:
        case = session.get(IdentityResolutionCase, case_id)
        assert case.reviewer_identity == "trusted-identity-editor"
        assert session.scalar(
            select(func.count()).select_from(PoliticianSourceIdentifier)
        ) == 1


def test_resolve_new_and_ignore_endpoints_have_expected_mutations(
    identity_api_context,
):
    new_case, ignored_case = identity_api_context.case_ids[1:]
    before_count = None
    with identity_api_context.session_factory() as session:
        before_count = session.scalar(select(func.count()).select_from(Politician))

    created = identity_api_context.client.post(
        f"/admin/identity-resolution/{new_case}/resolve-new",
        headers=identity_api_context.headers,
        json={"note": "Confirmed distinct official"},
    )
    ignored = identity_api_context.client.post(
        f"/admin/identity-resolution/{ignored_case}/ignore",
        headers=identity_api_context.headers,
        json={"note": "Insufficient evidence"},
    )

    assert created.status_code == 200
    assert created.json()["status"] == "resolved_new"
    assert created.json()["resolved_politician_id"] is not None
    assert ignored.status_code == 200
    assert ignored.json()["status"] == "ignored"
    assert ignored.json()["resolved_politician_id"] is None
    with identity_api_context.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Politician)) == (
            before_count + 1
        )
        assert session.scalar(
            select(func.count()).select_from(PoliticianSourceIdentifier)
        ) == 1


def test_public_routes_expose_no_identity_resolution_data(identity_api_context):
    direct = identity_api_context.client.get("/identity-resolution")
    public = identity_api_context.client.get(
        f"/politicians/{identity_api_context.existing_politician_id}"
    )

    assert direct.status_code == 404
    assert public.status_code == 404
    assert "identity_resolution" not in public.text
