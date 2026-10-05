from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import (
    Evidence,
    IdentityResolutionCase,
    IdentityResolutionStatus,
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
    ProfileDraft,
    ProfileDraftStatus,
    Proposal,
    ProposalDraft,
    ProposalDraftStatus,
    ProposalStatusEvent,
    Review,
)
from backend.app.services import PublishService
from scripts.prepare_demo import (
    DEMO_ADMIN_KEY,
    DemoPaths,
    DemoSafetyError,
    prepare_demo,
    reset_demo_environment,
)


def test_demo_setup_creates_published_and_pending_public_api_state(tmp_path):
    workspace = tmp_path / "workspace"
    summary = prepare_demo(workspace_root=workspace)

    assert summary.published_politician_id == 1
    assert summary.published_name == "Anna Rossi"
    assert summary.published_version_number == 1
    assert summary.published_citation_count == 14
    assert summary.pending_draft_id == 2
    assert summary.pending_politician_id == 2
    assert summary.pending_name == "Luca Bianchi"
    assert summary.pending_status is ProfileDraftStatus.PENDING
    assert summary.pending_evidence_count == 14
    assert summary.identity_resolution_case_id == 1
    assert summary.identity_resolution_name == "Carlo Verdi"
    assert summary.identity_resolution_status is IdentityResolutionStatus.PENDING
    assert summary.published_proposal_id == 1
    assert summary.pending_proposal_draft_id == 2

    app = create_app(
        Settings(
            database_url=f"sqlite:///{summary.database_path}",
            raw_storage_path=summary.raw_storage_path,
            admin_api_key=DEMO_ADMIN_KEY,
            admin_reviewer_identity="demo-presenter",
        )
    )
    with TestClient(app) as client:
        published = client.get("/politicians/1")
        pending = client.get("/politicians/2")
        listing = client.get("/politicians")
        draft = client.get(
            "/admin/drafts/2",
            headers={"Authorization": f"Bearer {DEMO_ADMIN_KEY}"},
        )
        proposal = client.get("/proposals/1")
        proposal_draft = client.get(
            "/admin/proposals/drafts/2",
            headers={"Authorization": f"Bearer {DEMO_ADMIN_KEY}"},
        )
        regions = client.get("/regions")
        municipalities = client.get("/municipalities")
        giulia = client.get("/politicians/3")

    assert published.status_code == 200
    assert published.json()["citation_count"] == 14
    assert len(published.json()["citations"]) == 14
    assert published.json()["parliamentary_groups"][0]["name"] == "Fratelli d'Italia"
    assert published.json()["political_parties"] == []
    assert pending.status_code == 404
    assert listing.json()["total"] == 2
    assert [item["id"] for item in listing.json()["items"]] == [3, 1]
    assert draft.status_code == 200
    assert draft.json()["status"] == "pending"
    assert len(draft.json()["evidence"]) == 14
    assert proposal.status_code == 200
    assert proposal.json()["current_status"] == "introduced"
    assert proposal_draft.json()["status"] == "pending"
    assert proposal_draft.json()["kind"] == "status_update"
    assert regions.json()["total"] == 1
    assert regions.json()["items"][0]["name"] == "Lombardia"
    assert municipalities.json()["items"][0]["name"] == "Milano"
    assert municipalities.json()["items"][0]["current_mayor"]["given_name"] == "Giulia"
    assert giulia.json()["territorial_offices"][0]["municipality"] == "Milano"


def test_demo_reset_is_repeatable_and_preserves_normal_development_data(tmp_path):
    workspace = tmp_path / "workspace"
    normal_database = workspace / "data" / "verapolitica.db"
    normal_raw_file = workspace / "data" / "raw" / "keep.bin"
    normal_database.parent.mkdir(parents=True)
    normal_database.write_bytes(b"normal-development-database")
    normal_raw_file.parent.mkdir(parents=True)
    normal_raw_file.write_bytes(b"normal-development-raw-data")

    first = prepare_demo(workspace_root=workspace)
    engine = create_db_engine(f"sqlite:///{first.database_path}")
    factory = create_session_factory(engine)
    PublishService(factory).approve(
        first.pending_draft_id,
        reviewer="rehearsal-editor",
    )
    engine.dispose()

    second = prepare_demo(workspace_root=workspace)

    assert second == first
    assert normal_database.read_bytes() == b"normal-development-database"
    assert normal_raw_file.read_bytes() == b"normal-development-raw-data"
    engine = create_db_engine(f"sqlite:///{second.database_path}")
    factory = create_session_factory(engine)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Politician)) == 3
        assert session.scalar(select(func.count()).select_from(ParliamentaryGroup)) == 2
        assert session.scalar(
            select(func.count()).select_from(ParliamentaryGroupMembership)
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(IdentityResolutionCase)
        ) == 1
        assert session.scalar(select(func.count()).select_from(ProfileDraft)) == 2
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 2
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(
            select(func.count()).select_from(PoliticianVersionCitation)
        ) == 15
        assert session.scalar(select(func.count()).select_from(Proposal)) == 1
        assert session.scalar(select(func.count()).select_from(ProposalDraft)) == 2
        assert session.scalar(
            select(func.count()).select_from(ProposalStatusEvent)
        ) == 1
        assert session.get(
            ProposalDraft, second.pending_proposal_draft_id
        ).status is ProposalDraftStatus.PENDING
        assert session.scalar(
            select(func.count())
            .select_from(Evidence)
            .where(Evidence.draft_id == second.pending_draft_id)
        ) == 14
        assert session.get(ProfileDraft, second.pending_draft_id).status is (
            ProfileDraftStatus.PENDING
        )
        assert session.get(Politician, second.pending_politician_id).current_version_id is None
        assert session.get(
            IdentityResolutionCase, second.identity_resolution_case_id
        ).status is IdentityResolutionStatus.PENDING
    engine.dispose()


def test_demo_reset_refuses_broad_or_unexpected_targets(tmp_path):
    workspace = (tmp_path / "workspace").resolve()
    data_root = workspace / "data"
    unsafe = DemoPaths(
        workspace_root=workspace,
        demo_root=data_root,
        database=data_root / "verapolitica_demo.db",
        raw_storage=data_root / "raw",
    )

    with pytest.raises(DemoSafetyError, match="exactly"):
        reset_demo_environment(unsafe)

    assert not (data_root / "verapolitica_demo.db").exists()
