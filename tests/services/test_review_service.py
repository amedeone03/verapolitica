from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.app.models import (
    ImmutableReviewError,
    Politician,
    PoliticianVersion,
    ProfileDraft,
    ProfileDraftKind,
    ProfileDraftStatus,
    RawDocument,
    RawDocumentStatus,
    Review,
    ReviewDecision,
)
from backend.app.services import (
    DraftNotReviewableError,
    ReviewService,
    normalize_person_name,
)


def profile_data(*, profession: str = "Avvocata") -> dict:
    return {
        "given_name": "Maria",
        "family_name": "Rossi",
        "birth_date": "1970-01-02",
        "birth_place": None,
        "gender": "female",
        "profession": profession,
        "image_url": None,
        "official_homepage_url": None,
        "mandates": [],
    }


def add_pending_draft(session_factory, source, *, status=ProfileDraftStatus.PENDING):
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        session.add(politician)
        session.flush()
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/review.json",
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
        draft = ProfileDraft(
            politician_id=politician.id,
            raw_document_id=document.id,
            kind=ProfileDraftKind.INITIAL,
            status=status,
            proposed_profile_data=profile_data(),
            diff_data={"status": "initial", "changes": []},
        )
        session.add(draft)
        session.commit()
        return draft.id, politician.id


def test_pending_draft_enters_in_review_without_creating_review(
    session_factory, source
):
    draft_id, politician_id = add_pending_draft(session_factory, source)

    result = ReviewService(session_factory).start_review(draft_id)

    assert result.status == "in_review"
    assert result.politician_id == politician_id
    with session_factory() as session:
        assert session.get(ProfileDraft, draft_id).status is ProfileDraftStatus.IN_REVIEW
        assert session.scalar(select(func.count()).select_from(Review)) == 0


def test_superseded_draft_cannot_be_reviewed(session_factory, source):
    draft_id, _ = add_pending_draft(
        session_factory, source, status=ProfileDraftStatus.SUPERSEDED
    )

    with pytest.raises(DraftNotReviewableError, match="superseded"):
        ReviewService(session_factory).start_review(draft_id)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 0


@pytest.mark.parametrize(
    "initial_status",
    [ProfileDraftStatus.PENDING, ProfileDraftStatus.IN_REVIEW],
)
def test_pending_or_in_review_draft_can_be_rejected(
    session_factory, source, initial_status
):
    draft_id, politician_id = add_pending_draft(
        session_factory, source, status=initial_status
    )

    result = ReviewService(session_factory).reject(
        draft_id,
        reviewer=" demo-editor ",
        note=" Evidence requires clarification ",
    )

    assert result.decision is ReviewDecision.REJECTED
    assert result.created_version_id is None
    assert result.version_number is None
    assert result.current_version_id is None
    assert result.final_draft_status is ProfileDraftStatus.REJECTED
    with session_factory() as session:
        draft = session.get(ProfileDraft, draft_id)
        review = session.get(Review, result.review_id)
        assert draft is not None and draft.status is ProfileDraftStatus.REJECTED
        assert review is not None
        assert review.draft_id == draft_id
        assert review.reviewer == "demo-editor"
        assert review.note == "Evidence requires clarification"
        assert review.decision is ReviewDecision.REJECTED
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0
        assert session.get(Politician, politician_id).current_version_id is None


def test_second_rejection_creates_no_additional_review(session_factory, source):
    draft_id, _ = add_pending_draft(session_factory, source)
    service = ReviewService(session_factory)
    service.reject(draft_id, reviewer="editor")

    with pytest.raises(DraftNotReviewableError, match="rejected"):
        service.reject(draft_id, reviewer="editor")

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 1
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0


def test_final_review_is_immutable(session_factory, source):
    draft_id, _ = add_pending_draft(session_factory, source)
    result = ReviewService(session_factory).reject(draft_id, reviewer="editor")

    with session_factory() as session:
        review = session.get(Review, result.review_id)
        assert review is not None
        review.note = "changed later"
        with pytest.raises(ImmutableReviewError):
            session.commit()
        session.rollback()
