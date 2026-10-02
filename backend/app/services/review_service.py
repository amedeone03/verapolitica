from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    ProfileDraft,
    ProfileDraftStatus,
    Review,
    ReviewDecision,
)
from backend.app.schemas import ReviewDecisionResult, ReviewStartedResult


class ReviewServiceError(RuntimeError):
    """Base error for controlled review workflow failures."""


class ReviewInputError(ReviewServiceError):
    """Reviewer identity or note is invalid."""


class DraftNotFoundError(ReviewServiceError):
    """The requested ProfileDraft does not exist."""


class DraftNotReviewableError(ReviewServiceError):
    """The draft is not in a state that accepts this review action."""


class ReviewConflictError(ReviewServiceError):
    """A final decision was created concurrently."""


class ReviewPersistenceError(ReviewServiceError):
    """Review persistence failed and its transaction was rolled back."""


def normalize_review_input(
    reviewer: str,
    note: str | None,
) -> tuple[str, str | None]:
    normalized_reviewer = reviewer.strip()
    if not normalized_reviewer:
        raise ReviewInputError("reviewer identity must be non-empty")
    if len(normalized_reviewer) > 200:
        raise ReviewInputError("reviewer identity must be at most 200 characters")
    normalized_note = note.strip() if note is not None else None
    return normalized_reviewer, normalized_note or None


class ReviewService:
    finalizable_statuses = (
        ProfileDraftStatus.PENDING,
        ProfileDraftStatus.IN_REVIEW,
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def start_review(self, draft_id: int) -> ReviewStartedResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_draft(session, draft_id)
                    if draft.status is not ProfileDraftStatus.PENDING:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} cannot enter review from "
                            f"status {draft.status.value!r}"
                        )
                    if draft.review is not None:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} already has a final Review"
                        )
                    draft.status = ProfileDraftStatus.IN_REVIEW
                    session.flush()
                    result = ReviewStartedResult(
                        draft_id=draft.id,
                        politician_id=draft.politician_id,
                    )
            return result
        except ReviewServiceError:
            raise
        except Exception as exc:
            raise ReviewPersistenceError(
                f"start-review failed; transaction rolled back: {exc}"
            ) from exc

    def reject(
        self,
        draft_id: int,
        *,
        reviewer: str,
        note: str | None = None,
    ) -> ReviewDecisionResult:
        normalized_reviewer, normalized_note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_draft(session, draft_id)
                    if draft.status not in self.finalizable_statuses:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} cannot be rejected from "
                            f"status {draft.status.value!r}"
                        )
                    if draft.review is not None:
                        raise DraftNotReviewableError(
                            f"draft {draft.id} already has a final Review"
                        )

                    review = Review(
                        draft_id=draft.id,
                        reviewer=normalized_reviewer,
                        decision=ReviewDecision.REJECTED,
                        note=normalized_note,
                    )
                    session.add(review)
                    draft.status = ProfileDraftStatus.REJECTED
                    session.flush()
                    result = ReviewDecisionResult(
                        review_id=review.id,
                        decision=review.decision,
                        draft_id=draft.id,
                        politician_id=draft.politician_id,
                        created_version_id=None,
                        version_number=None,
                        current_version_id=draft.politician.current_version_id,
                        final_draft_status=draft.status,
                    )
            return result
        except ReviewServiceError:
            raise
        except IntegrityError as exc:
            raise ReviewConflictError(
                "draft received another final decision; rejection rolled back"
            ) from exc
        except Exception as exc:
            raise ReviewPersistenceError(
                f"rejection failed; transaction rolled back: {exc}"
            ) from exc

    @staticmethod
    def _load_draft(session: Session, draft_id: int) -> ProfileDraft:
        draft = session.scalar(
            select(ProfileDraft)
            .where(ProfileDraft.id == draft_id)
            .with_for_update()
        )
        if draft is None:
            raise DraftNotFoundError(f"ProfileDraft {draft_id} does not exist")
        return draft
