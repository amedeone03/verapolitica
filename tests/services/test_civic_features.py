from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path

from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.jobs.runners import run_civic_reminders
from backend.app.models import RawDocument, RawDocumentStatus, Source
from backend.app.models.civic import (
    GeographicScopeType,
    NotificationEventType,
    Referendum,
    ReferendumDraftStatus,
    ReferendumStatus,
    ReferendumType,
)
from backend.app.pipeline.civic import map_referendum_fixture
from backend.app.schemas.civic import (
    GlossaryTermInput,
    ReferendumEvidenceObservation,
    ReferendumObservation,
    VotingGuideInput,
    VotingGuideSection,
)
from backend.app.schemas.search import SearchEntityType
from backend.app.services import (
    CivicContentService,
    NotificationService,
    PublicCivicQueryService,
    ReferendumReviewService,
    ReferendumService,
    SearchService,
)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "civic" / "historical_referendum_2026.json"
NOW = datetime(2026, 10, 6, 9, tzinfo=timezone.utc)


def _source_and_document(session, key="ministero-interno-elezioni"):
    source = Source(
        key=key,
        name="Ministero dell'Interno",
        base_url="https://dait.interno.gov.it",
    )
    session.add(source)
    session.flush()
    document = RawDocument(
        source_id=source.id,
        retrieved_at=NOW,
        source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
        content_type="application/json",
        storage_key=f"{key}/civic.json",
        raw_sha256="1" * 64,
        normalized_sha256="2" * 64,
        structured_records=[],
        process_status=RawDocumentStatus.PARSED,
        change_detected=True,
        collector_version="civic_v1",
        parser_version="civic_v1",
    )
    session.add(document)
    session.flush()
    return source, document


def _observation(document_id, **overrides):
    payload = {
        "source_key": "ministero-interno-elezioni",
        "raw_document_id": document_id,
        "official_identifier": "civic-test-1",
        "title": "Synthetic civic referendum (test)",
        "official_question": "Do you approve the synthetic civic test question?",
        "referendum_type": ReferendumType.CONSULTATIVE,
        "status": ReferendumStatus.SCHEDULED,
        "vote_date": date(2026, 11, 15),
        "vote_end_date": date(2026, 11, 16),
        "start_time": time(7, 0),
        "end_time": time(23, 0),
        "scope_type": GeographicScopeType.NATIONAL,
        "quorum_required": True,
        "quorum_description": "Synthetic quorum description for tests.",
        "official_source_url": "https://example.test/civic/test",
        "is_synthetic": True,
        "observed_at": NOW,
        "evidence": (
            ReferendumEvidenceObservation(
                field_path="title",
                source_url="https://example.test/civic/test",
                source_field="title",
                source_value="Synthetic civic referendum (test)",
            ),
            ReferendumEvidenceObservation(
                field_path="official_question",
                source_url="https://example.test/civic/test",
                source_field="question",
                source_value="Do you approve the synthetic civic test question?",
            ),
        ),
    }
    payload.update(overrides)
    return ReferendumObservation(**payload)


def test_referendum_source_identity_and_idempotency(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    first = ReferendumService(session_factory).sync((_observation(document_id),))
    second = ReferendumService(session_factory).sync((_observation(document_id),))
    assert first.created == 1
    assert second.already_observed == 1
    assert first.details[0].referendum_id == second.details[0].referendum_id
    with session_factory() as session:
        assert session.scalar(select(func.count(Referendum.id))) == 1


def test_unpublished_referendum_is_not_public(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    ReferendumService(session_factory).sync((_observation(document_id),))
    with session_factory() as session:
        public = PublicCivicQueryService(session).list_referendums(offset=0, limit=20)
        assert public.total == 0


def test_referendum_review_approve_and_reject(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync((_observation(document_id),))
    approved = ReferendumReviewService(session_factory).approve(
        created.details[0].draft_id, reviewer="editor"
    )
    assert approved.published is True
    with session_factory() as session:
        public = PublicCivicQueryService(session).get_referendum(
            created.details[0].referendum_id
        )
        assert public is not None
        assert public.is_synthetic is True
        assert public.quorum_required is True
        assert public.scope_type is GeographicScopeType.NATIONAL

    other = ReferendumService(session_factory).sync(
        (
            _observation(
                document_id,
                official_identifier="civic-test-reject",
                title="Rejected synthetic referendum",
            ),
        )
    )
    rejected = ReferendumReviewService(session_factory).reject(
        other.details[0].draft_id, reviewer="editor", note="Not ready"
    )
    assert rejected.final_draft_status is ReferendumDraftStatus.REJECTED
    with session_factory() as session:
        listing = PublicCivicQueryService(session).list_referendums(offset=0, limit=20)
        titles = [item.title for item in listing.items]
        assert "Rejected synthetic referendum" not in titles


def test_upcoming_filter_and_territorial_scope(session_factory):
    with session_factory() as session:
        from backend.app.models import Municipality, Region, TerritoryStatus

        source, document = _source_and_document(session)
        region = Region(
            istat_code="03",
            canonical_name="Lombardia",
            status=TerritoryStatus.ACTIVE,
            source_id=source.id,
            raw_document_id=document.id,
            source_url="https://example.test/istat",
        )
        session.add(region)
        session.flush()
        session.add(
            Municipality(
                istat_code="015146",
                region_id=region.id,
                canonical_name="Milano",
                province_abbreviation="MI",
                province_name="Milano",
                status=TerritoryStatus.ACTIVE,
                source_id=source.id,
                raw_document_id=document.id,
                source_url="https://example.test/istat",
            )
        )
        session.commit()
        document_id = document.id
    national = ReferendumService(session_factory).sync((_observation(document_id),))
    municipal = ReferendumService(session_factory).sync(
        (
            _observation(
                document_id,
                official_identifier="civic-milano",
                title="Synthetic Milano civic consultation",
                scope_type=GeographicScopeType.MUNICIPALITY,
                municipality_istat_code="015146",
            ),
        )
    )
    ReferendumReviewService(session_factory).approve(
        national.details[0].draft_id, reviewer="editor"
    )
    ReferendumReviewService(session_factory).approve(
        municipal.details[0].draft_id, reviewer="editor"
    )
    with session_factory() as session:
        upcoming = PublicCivicQueryService(session).list_referendums(
            offset=0, limit=20, upcoming=True, as_of=date(2026, 10, 6)
        )
        scoped = PublicCivicQueryService(session).list_referendums(
            offset=0, limit=20, scope=GeographicScopeType.MUNICIPALITY
        )
        detail = PublicCivicQueryService(session).get_referendum(
            municipal.details[0].referendum_id
        )
        assert upcoming.total == 2
        assert scoped.total == 1
        assert detail.municipality_name == "Milano"
        assert detail.region_name == "Lombardia"


def test_historical_fixture_parser_and_glossary_order(session_factory):
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    observation = map_referendum_fixture(
        record,
        source_key="ministero-interno-elezioni",
        raw_document_id=document_id,
        observed_at=NOW,
    )
    assert observation.referendum_type is ReferendumType.CONSTITUTIONAL
    assert observation.quorum_required is False
    assert observation.is_synthetic is False
    CivicContentService(session_factory).upsert_glossary_term(
        GlossaryTermInput(
            slug="quorum",
            term="Quorum",
            short_definition="Art. 75 participation majority.",
            source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
            source_key="ministero-interno-elezioni",
            publish=True,
        )
    )
    CivicContentService(session_factory).upsert_glossary_term(
        GlossaryTermInput(
            slug="legge",
            term="Legge",
            short_definition="Legislative function of the two Houses.",
            source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-70",
            source_key="ministero-interno-elezioni",
            publish=True,
        )
    )
    CivicContentService(session_factory).upsert_glossary_term(
        GlossaryTermInput(
            slug="hidden-term",
            term="Hidden",
            short_definition="Unpublished.",
            source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-70",
            source_key="ministero-interno-elezioni",
            publish=False,
        )
    )
    with session_factory() as session:
        listing = PublicCivicQueryService(session).list_glossary(offset=0, limit=20)
        assert [item.term for item in listing.items] == ["Legge", "Quorum"]
        assert listing.total == 2


def test_voting_guide_publication(session_factory):
    with session_factory() as session:
        _source_and_document(session)
        session.commit()
    CivicContentService(session_factory).upsert_voting_guide(
        VotingGuideInput(
            title="How to vote",
            scope=GeographicScopeType.NATIONAL,
            source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
            source_key="ministero-interno-elezioni",
            publish=False,
            sections=(
                VotingGuideSection(
                    key="eligibility",
                    title="Who can vote",
                    body="Citizens entitled to elect the Chamber of Deputies.",
                    source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
                ),
            ),
        )
    )
    with session_factory() as session:
        assert PublicCivicQueryService(session).list_voting_guides(offset=0, limit=10).total == 0
    CivicContentService(session_factory).upsert_voting_guide(
        VotingGuideInput(
            title="How to vote",
            scope=GeographicScopeType.NATIONAL,
            source_url="https://dait.interno.gov.it/elezioni/faq/faq-referendum-2026",
            source_key="ministero-interno-elezioni",
            publish=True,
            sections=(
                VotingGuideSection(
                    key="eligibility",
                    title="Who can vote",
                    body="Citizens entitled to elect the Chamber of Deputies.",
                    source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
                ),
            ),
        )
    )
    with session_factory() as session:
        assert PublicCivicQueryService(session).list_voting_guides(offset=0, limit=10).total == 1


def test_reminder_candidates_are_idempotent(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync((_observation(document_id),))
    ReferendumReviewService(session_factory).approve(
        created.details[0].draft_id, reviewer="editor"
    )
    first = NotificationService(session_factory).generate_reminder_candidates(
        as_of=date(2026, 11, 8)
    )
    second = NotificationService(session_factory).generate_reminder_candidates(
        as_of=date(2026, 11, 8)
    )
    assert first.created == 1
    assert second.created == 0
    assert second.already_present == 1
    day = NotificationService(session_factory).generate_reminder_candidates(
        as_of=date(2026, 11, 15)
    )
    assert day.created == 1


def test_search_includes_published_referendum_and_glossary(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync((_observation(document_id),))
    ReferendumReviewService(session_factory).approve(
        created.details[0].draft_id, reviewer="editor"
    )
    CivicContentService(session_factory).upsert_glossary_term(
        GlossaryTermInput(
            slug="quorum",
            term="Quorum",
            short_definition="Participation majority for abrogative referendums.",
            source_url="https://www.senato.it/istituzione/la-costituzione/parte-ii/titolo-i/sezione-ii/articolo-75",
            source_key="ministero-interno-elezioni",
            publish=True,
        )
    )
    with session_factory() as session:
        service = SearchService(session)
        referendum = service.search("synthetic civic", entity_type=SearchEntityType.REFERENDUM)
        glossary = service.search("quorum", entity_type=SearchEntityType.GLOSSARY_TERM)
        assert referendum.items[0].entity_type is SearchEntityType.REFERENDUM
        assert glossary.items[0].title == "Quorum"


def test_notification_subscription_is_idempotent(session_factory):
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync((_observation(document_id),))
    ReferendumReviewService(session_factory).approve(
        created.details[0].draft_id, reviewer="editor"
    )
    service = NotificationService(session_factory)
    first = service.subscribe(
        destination_token="token-abc123",
        event_type=NotificationEventType.REFERENDUM_UPCOMING,
        referendum_id=created.details[0].referendum_id,
    )
    second = service.subscribe(
        destination_token="token-abc123",
        event_type=NotificationEventType.REFERENDUM_UPCOMING,
        referendum_id=created.details[0].referendum_id,
    )
    assert first.id == second.id
    assert first.enabled is True


def test_civic_reminders_job_is_idempotent(session_factory):
    vote_date = date.today() + timedelta(days=7)
    with session_factory() as session:
        _source, document = _source_and_document(session)
        session.commit()
        document_id = document.id
    created = ReferendumService(session_factory).sync(
        (
            _observation(
                document_id,
                vote_date=vote_date,
                vote_end_date=vote_date,
            ),
        )
    )
    ReferendumReviewService(session_factory).approve(
        created.details[0].draft_id, reviewer="editor"
    )
    settings = Settings()
    first = run_civic_reminders(settings, session_factory)
    second = run_civic_reminders(settings, session_factory)
    assert first.records_created == 1
    assert second.records_created == 0
    assert second.records_skipped == 1
