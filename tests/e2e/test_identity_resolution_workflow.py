from datetime import datetime, timezone
from pathlib import Path

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
    Source,
)
from backend.app.pipeline.collectors import CollectedDocument
from backend.app.pipeline.ingestion_pipeline import IngestionPipeline
from backend.app.pipeline.mappers import GovernoCandidateProfileMapper
from backend.app.pipeline.parsers import GovernoParser
from backend.app.schemas import DraftCreatedResult, MatchedResult, MatchingMethod
from backend.app.services import (
    DraftService,
    HumanIdentityResolutionCoordinator,
    normalize_person_name,
)
from backend.app.storage import LocalRawStorage


FIXTURE = Path("data/fixtures/governo/governo_office_holders.json")


class GovernoFixtureCollector:
    version = "governo_e2e_fixture_v1"

    def collect(self) -> CollectedDocument:
        return CollectedDocument(
            content=FIXTURE.read_bytes(),
            source_url="https://www.governo.it/it/ministri-e-sottosegretari",
            content_type="application/vnd.verapolitica.governo-bundle+json",
            retrieved_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
            collector_version=self.version,
        )


def test_governo_manual_identity_resolution_continues_to_publication(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'identity-e2e.db'}"
    raw_path = tmp_path / "raw"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=raw_path,
        admin_api_key="e2e-identity-admin",
        admin_reviewer_identity="e2e-human-editor",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        governo = Source(
            key="governo-italiano",
            name="Governo Italiano",
            base_url="https://www.governo.it",
        )
        senato = Source(
            key="senato-repubblica",
            name="Senato della Repubblica",
            base_url="https://dati.senato.it",
        )
        session.add_all((governo, senato))
        session.flush()
        existing = Politician(
            canonical_given_name="Carlo",
            canonical_family_name="Verdi",
            normalized_name=normalize_person_name("Carlo", "Verdi"),
            birth_date=None,
        )
        session.add(existing)
        session.flush()
        session.add(
            PoliticianSourceIdentifier(
                politician_id=existing.id,
                source_id=senato.id,
                value="senato-person-carlo-verdi",
            )
        )
        session.commit()
        governo_id = governo.id
        existing_id = existing.id

    ingestion = IngestionPipeline(
        session_factory=session_factory,
        storage=LocalRawStorage(raw_path),
        collector=GovernoFixtureCollector(),
        parser=GovernoParser(),
        profile_mapper=GovernoCandidateProfileMapper(),
    ).run(source_id=governo_id, source_key="governo-italiano")
    candidate = next(
        item
        for item in ingestion.candidate_profiles
        if item.identity.display_name == "Carlo Verdi"
    )
    coordinator = HumanIdentityResolutionCoordinator(session_factory)
    unresolved = coordinator.process(candidate)
    assert unresolved.case is not None
    case_id = unresolved.case.case_id
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Politician)) == 1
        assert session.scalar(
            select(func.count()).select_from(IdentityResolutionCase)
        ) == 1

    app = create_app(settings)
    headers = {"Authorization": "Bearer e2e-identity-admin"}
    with TestClient(app) as client:
        before_public = client.get(f"/politicians/{existing_id}")
        case_detail = client.get(
            f"/admin/identity-resolution/{case_id}",
            headers=headers,
        )
        resolved = client.post(
            f"/admin/identity-resolution/{case_id}/resolve-existing",
            headers=headers,
            json={
                "politician_id": existing_id,
                "note": "Senato and Governo profiles manually verified",
            },
        )

        assert before_public.status_code == 404
        assert case_detail.status_code == 200
        assert case_detail.json()["candidate_display_name"] == "Carlo Verdi"
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved_existing"

        future = coordinator.process(candidate)
        assert future.match == MatchedResult(
            politician_id=existing_id,
            method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
        )
        assert future.case is None
        with session_factory() as session:
            assert session.scalar(
                select(func.count()).select_from(IdentityResolutionCase)
            ) == 1
            governo_identifier = session.scalar(
                select(PoliticianSourceIdentifier)
                .join(Source)
                .where(
                    Source.key == "governo-italiano",
                    PoliticianSourceIdentifier.politician_id == existing_id,
                )
            )
            assert governo_identifier is not None

        draft = DraftService(session_factory).create(candidate, future.match)
        assert isinstance(draft, DraftCreatedResult)
        started = client.post(
            f"/admin/drafts/{draft.draft_id}/start-review",
            headers=headers,
        )
        approved = client.post(
            f"/admin/drafts/{draft.draft_id}/approve",
            headers=headers,
            json={"note": "Official Governo evidence verified"},
        )
        after_public = client.get(f"/politicians/{existing_id}")

        assert started.status_code == 200
        assert approved.status_code == 200
        assert approved.json()["final_draft_status"] == "approved"
        assert after_public.status_code == 200
        assert after_public.json()["given_name"] == "Carlo"
        assert after_public.json()["citation_count"] > 0

    engine.dispose()
