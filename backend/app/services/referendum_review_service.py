from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Source
from backend.app.models.civic import (
    GeographicScopeType,
    Referendum,
    ReferendumDraft,
    ReferendumDraftStatus,
    ReferendumReview,
    ReferendumReviewDecision,
)
from backend.app.schemas.civic import (
    ReferendumObservation,
    ReferendumReviewResult,
    ReferendumReviewStarted,
)
from backend.app.services.referendum_service import ReferendumService
from backend.app.services.review_service import normalize_review_input


class ReferendumReviewServiceError(RuntimeError):
    pass


class ReferendumDraftNotFoundError(ReferendumReviewServiceError):
    pass


class ReferendumDraftNotReviewableError(ReferendumReviewServiceError):
    pass


class ReferendumReviewConflictError(ReferendumReviewServiceError):
    pass


class ReferendumReviewPersistenceError(ReferendumReviewServiceError):
    pass


class ReferendumReviewService:
    finalizable_statuses = (
        ReferendumDraftStatus.PENDING,
        ReferendumDraftStatus.IN_REVIEW,
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def start_review(self, draft_id: int) -> ReferendumReviewStarted:
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_draft(session, draft_id)
                    if draft.status is not ReferendumDraftStatus.PENDING:
                        raise ReferendumDraftNotReviewableError(
                            f"referendum draft {draft.id} cannot enter review from "
                            f"status {draft.status.value!r}"
                        )
                    if draft.review is not None:
                        raise ReferendumDraftNotReviewableError(
                            f"referendum draft {draft.id} already has a final review"
                        )
                    draft.status = ReferendumDraftStatus.IN_REVIEW
                    session.flush()
                    result = ReferendumReviewStarted(
                        draft_id=draft.id,
                        referendum_id=draft.referendum_id,
                        final_draft_status=draft.status,
                    )
            return result
        except ReferendumReviewServiceError:
            raise
        except Exception as exc:
            raise ReferendumReviewPersistenceError(
                f"referendum start-review failed; transaction rolled back: {exc}"
            ) from exc

    def reject(
        self, draft_id: int, *, reviewer: str, note: str | None = None
    ) -> ReferendumReviewResult:
        reviewer, note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_finalizable(session, draft_id, "rejected")
                    review = ReferendumReview(
                        draft_id=draft.id,
                        reviewer=reviewer,
                        decision=ReferendumReviewDecision.REJECTED,
                        note=note,
                    )
                    session.add(review)
                    draft.status = ReferendumDraftStatus.REJECTED
                    session.flush()
                    result = ReferendumReviewResult(
                        review_id=review.id,
                        draft_id=draft.id,
                        referendum_id=draft.referendum_id,
                        decision=review.decision,
                        final_draft_status=draft.status,
                        published=False,
                    )
            return result
        except ReferendumReviewServiceError:
            raise
        except IntegrityError as exc:
            raise ReferendumReviewConflictError(
                "referendum draft received another final decision; rejection rolled back"
            ) from exc
        except Exception as exc:
            raise ReferendumReviewPersistenceError(
                f"referendum rejection failed; transaction rolled back: {exc}"
            ) from exc

    def approve(
        self, draft_id: int, *, reviewer: str, note: str | None = None
    ) -> ReferendumReviewResult:
        reviewer, note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_finalizable(session, draft_id, "approved")
                    observation = self._parse_observation(draft)
                    referendum = session.scalar(
                        select(Referendum)
                        .where(Referendum.id == draft.referendum_id)
                        .with_for_update()
                    )
                    if referendum is None:
                        raise ReferendumDraftNotFoundError(
                            f"Referendum {draft.referendum_id} does not exist"
                        )
                    region, municipality = ReferendumService._resolve_scope(
                        session, observation
                    )
                    source = session.scalar(
                        select(Source).where(Source.key == observation.source_key)
                    )
                    if source is None:
                        raise ReferendumReviewConflictError(
                            f"referendum source {observation.source_key!r} no longer exists"
                        )
                    referendum.title = observation.title
                    referendum.official_question = observation.official_question
                    referendum.referendum_type = observation.referendum_type
                    referendum.status = observation.status
                    referendum.vote_date = observation.vote_date
                    referendum.vote_end_date = observation.vote_end_date
                    referendum.start_time = observation.start_time
                    referendum.end_time = observation.end_time
                    referendum.voting_hours_description = (
                        observation.voting_hours_description
                    )
                    referendum.scope_type = observation.scope_type
                    referendum.region_id = region.id if region else None
                    referendum.municipality_id = (
                        municipality.id if municipality else None
                    )
                    if observation.scope_type is GeographicScopeType.MUNICIPALITY:
                        if municipality is None:
                            raise ReferendumReviewConflictError(
                                "municipal referendum is missing its municipality"
                            )
                        referendum.region_id = municipality.region_id
                    referendum.quorum_required = observation.quorum_required
                    referendum.quorum_description = observation.quorum_description
                    referendum.official_source_url = str(observation.official_source_url)
                    referendum.is_synthetic = observation.is_synthetic
                    if referendum.published_at is None:
                        referendum.published_at = datetime.now(timezone.utc)
                    review = ReferendumReview(
                        draft_id=draft.id,
                        reviewer=reviewer,
                        decision=ReferendumReviewDecision.APPROVED,
                        note=note,
                    )
                    session.add(review)
                    draft.status = ReferendumDraftStatus.APPROVED
                    session.flush()
                    result = ReferendumReviewResult(
                        review_id=review.id,
                        draft_id=draft.id,
                        referendum_id=referendum.id,
                        decision=review.decision,
                        final_draft_status=draft.status,
                        published=True,
                    )
            return result
        except ReferendumReviewServiceError:
            raise
        except IntegrityError as exc:
            raise ReferendumReviewConflictError(
                "referendum draft received another final decision; approval rolled back"
            ) from exc
        except Exception as exc:
            raise ReferendumReviewPersistenceError(
                f"referendum approval failed; transaction rolled back: {exc}"
            ) from exc

    def _load_draft(self, session: Session, draft_id: int) -> ReferendumDraft:
        draft = session.scalar(
            select(ReferendumDraft).where(ReferendumDraft.id == draft_id)
        )
        if draft is None:
            raise ReferendumDraftNotFoundError(
                f"ReferendumDraft {draft_id} does not exist"
            )
        return draft

    def _load_finalizable(
        self, session: Session, draft_id: int, action: str
    ) -> ReferendumDraft:
        draft = self._load_draft(session, draft_id)
        if draft.status not in self.finalizable_statuses:
            raise ReferendumDraftNotReviewableError(
                f"referendum draft {draft.id} cannot be {action} from status "
                f"{draft.status.value!r}"
            )
        if draft.review is not None:
            raise ReferendumDraftNotReviewableError(
                f"referendum draft {draft.id} already has a final review"
            )
        return draft

    @staticmethod
    def _parse_observation(draft: ReferendumDraft) -> ReferendumObservation:
        try:
            return ReferendumObservation.model_validate(draft.proposed_data)
        except ValidationError as exc:
            raise ReferendumDraftNotReviewableError(
                f"referendum draft {draft.id} has invalid proposed data: {exc}"
            ) from exc
