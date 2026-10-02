from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event, func, select

from backend.app.models import (
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
from backend.app.schemas import PoliticianVersionProfile
from backend.app.services import (
    DraftNotReviewableError,
    PublishPersistenceError,
    PublishService,
    StaleDraftError,
    normalize_person_name,
)


def profile_data(*, profession: str = "Avvocata") -> dict:
    return {
        "given_name": "Maria",
        "family_name": "Rossi",
        "birth_date": "1970-01-02",
        "birth_place": {"city": "Roma", "subdivision": "RM", "country": "Italia"},
        "gender": "female",
        "profession": profession,
        "image_url": None,
        "official_homepage_url": "https://example.test/profile",
        "mandates": [
            {
                "institution": "Senato della Repubblica",
                "office": "senator",
                "legislature": "19",
                "mandate_type": "elettivo",
                "start_date": "2022-10-13",
                "end_date": None,
                "election_area": "Lazio",
            }
        ],
    }


def add_politician_and_document(session_factory, source):
    with session_factory() as session:
        politician = Politician(
            canonical_given_name="Maria",
            canonical_family_name="Rossi",
            normalized_name=normalize_person_name("Maria", "Rossi"),
            birth_date=date(1970, 1, 2),
        )
        document = RawDocument(
            source_id=source.id,
            retrieved_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            source_url="https://dati.senato.it/sparql",
            content_type="application/json",
            storage_key="senato/publish.json",
            raw_sha256="a" * 64,
            normalized_sha256="b" * 64,
            structured_records=[],
            process_status=RawDocumentStatus.PARSED,
            change_detected=True,
            collector_version="senato_collector_v1",
            parser_version="senato_parser_v1",
        )
        session.add_all([politician, document])
        session.commit()
        return politician.id, document.id


def add_version(
    session_factory,
    politician_id,
    *,
    number: int,
    profile=None,
    make_current: bool = True,
) -> int:
    with session_factory() as session:
        version = PoliticianVersion(
            politician_id=politician_id,
            version_number=number,
            profile_schema_version=1,
            profile_data=profile or profile_data(),
            published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        session.add(version)
        session.flush()
        if make_current:
            politician = session.get(Politician, politician_id)
            assert politician is not None
            politician.current_version_id = version.id
        session.commit()
        return version.id


def add_draft(
    session_factory,
    politician_id,
    raw_document_id,
    *,
    kind=ProfileDraftKind.INITIAL,
    status=ProfileDraftStatus.PENDING,
    baseline_version_id=None,
    proposed=None,
) -> int:
    with session_factory() as session:
        draft = ProfileDraft(
            politician_id=politician_id,
            baseline_version_id=baseline_version_id,
            raw_document_id=raw_document_id,
            kind=kind,
            status=status,
            profile_schema_version=1,
            proposed_profile_data=proposed or profile_data(),
            diff_data={"status": kind.value, "changes": []},
        )
        session.add(draft)
        session.commit()
        return draft.id


def counts(session_factory) -> tuple[int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(PoliticianVersion)),
            session.scalar(select(func.count()).select_from(Review)),
        )


def test_initial_approval_atomically_creates_version_review_and_pointer(
    session_factory, source
):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    draft_id = add_draft(session_factory, politician_id, document_id)

    result = PublishService(session_factory).approve(
        draft_id,
        reviewer="demo-editor",
        note="Official evidence verified",
    )

    assert result.decision is ReviewDecision.APPROVED
    assert result.version_number == 1
    assert result.created_version_id == result.current_version_id
    assert result.final_draft_status is ProfileDraftStatus.APPROVED
    with session_factory() as session:
        draft = session.get(ProfileDraft, draft_id)
        version = session.get(PoliticianVersion, result.created_version_id)
        review = session.get(Review, result.review_id)
        politician = session.get(Politician, politician_id)
        assert draft is not None and draft.status is ProfileDraftStatus.APPROVED
        assert version is not None and version.published_at is not None
        assert version.version_number == 1
        assert version.profile_data == PoliticianVersionProfile.model_validate(
            draft.proposed_profile_data
        ).model_dump(mode="json")
        assert politician is not None
        assert politician.current_version_id == version.id
        assert review is not None and review.decision is ReviewDecision.APPROVED
        assert review.reviewer == "demo-editor"
        assert review.note == "Official evidence verified"


def test_update_approval_creates_next_unique_version(session_factory, source):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    first_version_id = add_version(
        session_factory,
        politician_id,
        number=1,
        profile=profile_data(profession="Avvocata"),
    )
    draft_id = add_draft(
        session_factory,
        politician_id,
        document_id,
        kind=ProfileDraftKind.UPDATE,
        status=ProfileDraftStatus.IN_REVIEW,
        baseline_version_id=first_version_id,
        proposed=profile_data(profession="Magistrata"),
    )

    result = PublishService(session_factory).approve(
        draft_id, reviewer="demo-editor"
    )

    assert result.version_number == 2
    with session_factory() as session:
        versions = list(
            session.scalars(
                select(PoliticianVersion)
                .where(PoliticianVersion.politician_id == politician_id)
                .order_by(PoliticianVersion.version_number)
            )
        )
        assert [version.version_number for version in versions] == [1, 2]
        assert versions[1].profile_data["profession"] == "Magistrata"
        assert session.get(Politician, politician_id).current_version_id == versions[1].id


def test_approval_failure_rolls_back_every_publication_write(session_factory, source):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    draft_id = add_draft(session_factory, politician_id, document_id)

    def fail_review_insert(mapper, connection, target):
        raise RuntimeError("injected Review failure")

    event.listen(Review, "before_insert", fail_review_insert)
    try:
        with pytest.raises(PublishPersistenceError, match="rolled back"):
            PublishService(session_factory).approve(
                draft_id, reviewer="demo-editor"
            )
    finally:
        event.remove(Review, "before_insert", fail_review_insert)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Review)) == 0
        assert session.scalar(select(func.count()).select_from(PoliticianVersion)) == 0
        assert session.get(Politician, politician_id).current_version_id is None
        assert session.get(ProfileDraft, draft_id).status is ProfileDraftStatus.PENDING


def test_stale_initial_draft_is_blocked_before_writes(session_factory, source):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    draft_id = add_draft(session_factory, politician_id, document_id)
    existing_version_id = add_version(session_factory, politician_id, number=1)

    with pytest.raises(StaleDraftError, match="now has version"):
        PublishService(session_factory).approve(draft_id, reviewer="editor")

    assert counts(session_factory) == (1, 0)
    with session_factory() as session:
        assert session.get(Politician, politician_id).current_version_id == existing_version_id
        assert session.get(ProfileDraft, draft_id).status is ProfileDraftStatus.PENDING


def test_stale_update_draft_is_blocked_before_writes(session_factory, source):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    first_id = add_version(session_factory, politician_id, number=1)
    draft_id = add_draft(
        session_factory,
        politician_id,
        document_id,
        kind=ProfileDraftKind.UPDATE,
        baseline_version_id=first_id,
        proposed=profile_data(profession="Magistrata"),
    )
    second_id = add_version(
        session_factory,
        politician_id,
        number=2,
        profile=profile_data(profession="Docente"),
    )

    with pytest.raises(StaleDraftError, match="expected current version"):
        PublishService(session_factory).approve(draft_id, reviewer="editor")

    assert counts(session_factory) == (2, 0)
    with session_factory() as session:
        assert session.get(Politician, politician_id).current_version_id == second_id
        assert session.get(ProfileDraft, draft_id).status is ProfileDraftStatus.PENDING


@pytest.mark.parametrize(
    "status",
    [
        ProfileDraftStatus.SUPERSEDED,
        ProfileDraftStatus.REJECTED,
        ProfileDraftStatus.FAILED,
        ProfileDraftStatus.APPROVED,
    ],
)
def test_terminal_drafts_cannot_be_published(session_factory, source, status):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    draft_id = add_draft(
        session_factory,
        politician_id,
        document_id,
        status=status,
    )

    with pytest.raises(DraftNotReviewableError, match=status.value):
        PublishService(session_factory).approve(draft_id, reviewer="editor")

    assert counts(session_factory) == (0, 0)


def test_second_approval_creates_no_additional_records(session_factory, source):
    politician_id, document_id = add_politician_and_document(session_factory, source)
    draft_id = add_draft(session_factory, politician_id, document_id)
    service = PublishService(session_factory)
    first = service.approve(draft_id, reviewer="editor")

    with pytest.raises(DraftNotReviewableError, match="approved"):
        service.approve(draft_id, reviewer="editor")

    assert counts(session_factory) == (1, 1)
    with session_factory() as session:
        assert session.get(Politician, politician_id).current_version_id == first.created_version_id
