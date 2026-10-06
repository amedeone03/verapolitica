from datetime import date, datetime, time, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.models.civic import (
    GeographicScopeType,
    NotificationReminderCandidate,
    ReferendumDraft,
    ReferendumStatus,
    ReferendumType,
)
from backend.app.schemas.civic import ReferendumEvidenceObservation, ReferendumObservation
from backend.app.services import NotificationService, ReferendumService


ADMIN = {"Authorization": "Bearer civic-e2e"}
NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def test_referendum_editorial_and_reminder_e2e(tmp_path, session_factory):
    settings = Settings(
        database_url=str(session_factory.kw["bind"].url),
        raw_storage_path=tmp_path / "raw",
        admin_api_key="civic-e2e",
    )
    with session_factory() as session:
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
            source_url="https://example.test/civic-e2e",
            content_type="application/json",
            storage_key="civic-e2e.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="e2e",
            parser_version="e2e",
        )
        session.add(document)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync(
        (
            ReferendumObservation(
                source_key="ministero-interno-elezioni",
                raw_document_id=document_id,
                official_identifier="civic-e2e-1",
                title="Synthetic civic referendum (E2E)",
                official_question="Synthetic E2E official question",
                referendum_type=ReferendumType.CONSULTATIVE,
                status=ReferendumStatus.SCHEDULED,
                vote_date=date(2026, 11, 15),
                start_time=time(7, 0),
                end_time=time(23, 0),
                scope_type=GeographicScopeType.NATIONAL,
                quorum_required=True,
                quorum_description="Synthetic quorum",
                official_source_url="https://example.test/civic-e2e",
                is_synthetic=True,
                observed_at=NOW,
                evidence=(
                    ReferendumEvidenceObservation(
                        field_path="title",
                        source_url="https://example.test/civic-e2e",
                        source_field="title",
                        source_value="Synthetic civic referendum (E2E)",
                    ),
                ),
            ),
        )
    )
    draft_id = created.details[0].draft_id
    referendum_id = created.details[0].referendum_id
    with TestClient(create_app(settings)) as client:
        assert client.get("/referendums").json()["total"] == 0
        assert client.get(f"/referendums/{referendum_id}").status_code == 404
        page = client.get("/app/?view=referendums")
        assert page.status_code == 200
        assert "Referendums and voting events" in page.text
        started = client.post(
            f"/admin/referendums/drafts/{draft_id}/start-review",
            headers=ADMIN,
        )
        approved = client.post(
            f"/admin/referendums/drafts/{draft_id}/approve",
            headers=ADMIN,
            json={"note": "e2e"},
        )
        assert started.status_code == 200
        assert approved.status_code == 200
        public = client.get(f"/referendums/{referendum_id}")
        assert public.status_code == 200
        assert public.json()["title"].startswith("Synthetic civic")
        script = client.get("/app/app.js").text
        assert "renderReferendumCard" in script
        assert "How to vote" in client.get("/app/?view=voting-guide").text
        assert "Key terms" in client.get("/app/?view=glossary").text
    first = NotificationService(session_factory).generate_reminder_candidates(
        as_of=date(2026, 11, 8)
    )
    replay = NotificationService(session_factory).generate_reminder_candidates(
        as_of=date(2026, 11, 8)
    )
    assert first.created == 1
    assert replay.created == 0
    with session_factory() as session:
        count = session.scalar(select(func.count(NotificationReminderCandidate.id)))
        drafts = session.scalar(select(func.count(ReferendumDraft.id)))
        assert count == 1
        assert drafts == 1
