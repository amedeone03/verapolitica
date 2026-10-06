from datetime import date, datetime, time, timezone

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.models.civic import (
    GeographicScopeType,
    ReferendumStatus,
    ReferendumType,
)
from backend.app.schemas.civic import ReferendumEvidenceObservation, ReferendumObservation
from backend.app.services import ReferendumService


NOW = datetime(2026, 10, 6, 9, tzinfo=timezone.utc)
ADMIN = {"Authorization": "Bearer civic-admin"}


def _app(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'civic-api.db'}"
    settings = Settings(
        database_url=database_url,
        raw_storage_path=tmp_path / "raw",
        admin_api_key="civic-admin",
    )
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        source = Source(
            key="ministero-interno-elezioni",
            name="Ministero dell'Interno",
            base_url="https://dait.interno.gov.it",
        )
        session.add(source)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=NOW,
            source_url="https://example.test/civic",
            content_type="application/json",
            storage_key="civic.json",
            raw_sha256="1" * 64,
            normalized_sha256="2" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="v1",
            parser_version="v1",
        )
        session.add(document)
        session.commit()
        document_id = document.id
    observation = ReferendumObservation(
        source_key="ministero-interno-elezioni",
        raw_document_id=document_id,
        official_identifier="civic-api-1",
        title="Synthetic civic referendum (API)",
        official_question="Synthetic official question",
        referendum_type=ReferendumType.CONSULTATIVE,
        status=ReferendumStatus.SCHEDULED,
        vote_date=date(2026, 11, 15),
        start_time=time(7, 0),
        end_time=time(23, 0),
        scope_type=GeographicScopeType.NATIONAL,
        quorum_required=True,
        quorum_description="Synthetic quorum",
        official_source_url="https://example.test/civic",
        is_synthetic=True,
        observed_at=NOW,
        evidence=(
            ReferendumEvidenceObservation(
                field_path="title",
                source_url="https://example.test/civic",
                source_field="title",
                source_value="Synthetic civic referendum (API)",
            ),
        ),
    )
    created = ReferendumService(factory).sync((observation,))
    engine.dispose()
    return TestClient(create_app(settings)), created.details[0]


def test_public_civic_apis_hide_unpublished_and_expose_approved(tmp_path):
    client, detail = _app(tmp_path)
    with client:
        hidden = client.get("/referendums")
        missing = client.get("/referendums/1")
        drafts = client.get("/admin/referendums/drafts", headers=ADMIN)
        assert hidden.status_code == 200
        assert hidden.json()["total"] == 0
        assert missing.status_code == 404
        assert drafts.status_code == 200
        assert drafts.json()["total"] == 1
        started = client.post(
            f"/admin/referendums/drafts/{detail.draft_id}/start-review",
            headers=ADMIN,
        )
        approved = client.post(
            f"/admin/referendums/drafts/{detail.draft_id}/approve",
            headers=ADMIN,
            json={"note": "ok"},
        )
        assert started.status_code == 200
        assert approved.status_code == 200
        listing = client.get("/referendums?upcoming=true")
        item = client.get(f"/referendums/{detail.referendum_id}")
        glossary = client.get("/glossary")
        guides = client.get("/voting-guides")
        assert listing.json()["total"] == 1
        assert item.json()["official_question"] == "Synthetic official question"
        assert item.json()["is_synthetic"] is True
        assert glossary.status_code == 200
        assert guides.status_code == 200
        assert "draft" not in str(item.json()).casefold()
