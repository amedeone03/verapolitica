from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Proposal,
    ProposalActor,
    ProposalActorRole,
    ProposalActorType,
    ProposalDraft,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalReview,
    ProposalReviewDecision,
    ProposalSourceIdentifier,
    ProposalStatusEvent,
    Source,
)
from backend.app.schemas import (
    ProposalObservation,
    ProposalReviewResult,
    ProposalReviewStarted,
)
from backend.app.services.proposal_service import ProposalService
from backend.app.services.review_service import normalize_review_input


class ProposalReviewServiceError(RuntimeError):
    pass


class ProposalDraftNotFoundError(ProposalReviewServiceError):
    pass


class ProposalDraftNotReviewableError(ProposalReviewServiceError):
    pass


class ProposalDraftStaleError(ProposalReviewServiceError):
    pass


class ProposalReviewConflictError(ProposalReviewServiceError):
    pass


class ProposalReviewPersistenceError(ProposalReviewServiceError):
    pass


class ProposalReviewService:
    finalizable_statuses = (
        ProposalDraftStatus.PENDING,
        ProposalDraftStatus.IN_REVIEW,
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def start_review(self, draft_id: int) -> ProposalReviewStarted:
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_draft(session, draft_id)
                    if draft.status is not ProposalDraftStatus.PENDING:
                        raise ProposalDraftNotReviewableError(
                            f"proposal draft {draft.id} cannot enter review from "
                            f"status {draft.status.value!r}"
                        )
                    if draft.review is not None:
                        raise ProposalDraftNotReviewableError(
                            f"proposal draft {draft.id} already has a final review"
                        )
                    draft.status = ProposalDraftStatus.IN_REVIEW
                    session.flush()
                    result = ProposalReviewStarted(
                        draft_id=draft.id,
                        proposal_id=draft.proposal_id,
                        final_draft_status=draft.status,
                    )
            return result
        except ProposalReviewServiceError:
            raise
        except Exception as exc:
            raise ProposalReviewPersistenceError(
                f"proposal start-review failed; transaction rolled back: {exc}"
            ) from exc

    def reject(
        self, draft_id: int, *, reviewer: str, note: str | None = None
    ) -> ProposalReviewResult:
        reviewer, note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_finalizable(session, draft_id, "rejected")
                    review = ProposalReview(
                        draft_id=draft.id,
                        reviewer=reviewer,
                        decision=ProposalReviewDecision.REJECTED,
                        note=note,
                    )
                    session.add(review)
                    draft.status = ProposalDraftStatus.REJECTED
                    session.flush()
                    result = ProposalReviewResult(
                        review_id=review.id,
                        draft_id=draft.id,
                        proposal_id=draft.proposal_id,
                        decision=review.decision,
                        final_draft_status=draft.status,
                    )
            return result
        except ProposalReviewServiceError:
            raise
        except IntegrityError as exc:
            raise ProposalReviewConflictError(
                "proposal draft received another final decision; rejection rolled back"
            ) from exc
        except Exception as exc:
            raise ProposalReviewPersistenceError(
                f"proposal rejection failed; transaction rolled back: {exc}"
            ) from exc

    def approve(
        self, draft_id: int, *, reviewer: str, note: str | None = None
    ) -> ProposalReviewResult:
        reviewer, note = normalize_review_input(reviewer, note)
        try:
            with self.session_factory() as session:
                with session.begin():
                    draft = self._load_finalizable(session, draft_id, "approved")
                    observation = self._parse_observation(draft)
                    ProposalService._validate_evidence(observation)
                    proposal = session.scalar(
                        select(Proposal)
                        .where(Proposal.id == draft.proposal_id)
                        .with_for_update()
                    )
                    if proposal is None:
                        raise ProposalDraftNotFoundError(
                            f"Proposal {draft.proposal_id} does not exist"
                        )
                    latest = ProposalService._latest_status_event(session, proposal.id)
                    self._validate_baseline(draft, proposal, latest)
                    ProposalService._validate_chronology(
                        session, proposal, observation
                    )

                    source = session.scalar(
                        select(Source).where(Source.key == observation.source_key)
                    )
                    if source is None:
                        raise ProposalReviewConflictError(
                            f"proposal source {observation.source_key!r} no longer exists"
                        )
                    self._publish_actors(session, proposal, observation)
                    event = self._publish_status_event(
                        session,
                        proposal=proposal,
                        draft=draft,
                        source=source,
                        observation=observation,
                    )
                    proposal.canonical_title = observation.title
                    proposal.summary = observation.summary
                    proposal.exact_statement = observation.exact_statement
                    proposal.proposal_type = observation.proposal_type
                    proposal.introduced_at = observation.introduced_at
                    if event is not None:
                        proposal.current_status = event.normalized_status
                    if proposal.published_at is None:
                        proposal.published_at = datetime.now(timezone.utc)
                    identifier = session.scalar(
                        select(ProposalSourceIdentifier).where(
                            ProposalSourceIdentifier.proposal_id == proposal.id,
                            ProposalSourceIdentifier.source_id == source.id,
                            ProposalSourceIdentifier.official_identifier
                            == observation.proposal_identifier,
                        )
                    )
                    if identifier is None:
                        raise ProposalReviewConflictError(
                            "proposal official identity is missing at publication time"
                        )
                    identifier.source_url = str(observation.official_url)

                    review = ProposalReview(
                        draft_id=draft.id,
                        reviewer=reviewer,
                        decision=ProposalReviewDecision.APPROVED,
                        note=note,
                    )
                    session.add(review)
                    draft.status = ProposalDraftStatus.APPROVED
                    session.flush()
                    result = ProposalReviewResult(
                        review_id=review.id,
                        draft_id=draft.id,
                        proposal_id=proposal.id,
                        decision=review.decision,
                        final_draft_status=draft.status,
                        created_status_event_id=event.id if event else None,
                    )
            return result
        except ProposalReviewServiceError:
            raise
        except IntegrityError as exc:
            raise ProposalReviewConflictError(
                "proposal approval conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise ProposalReviewPersistenceError(
                f"proposal approval failed; transaction rolled back: {exc}"
            ) from exc

    @staticmethod
    def _load_draft(session: Session, draft_id: int) -> ProposalDraft:
        draft = session.scalar(
            select(ProposalDraft)
            .where(ProposalDraft.id == draft_id)
            .with_for_update()
        )
        if draft is None:
            raise ProposalDraftNotFoundError(
                f"ProposalDraft {draft_id} does not exist"
            )
        return draft

    def _load_finalizable(
        self, session: Session, draft_id: int, action: str
    ) -> ProposalDraft:
        draft = self._load_draft(session, draft_id)
        if draft.status not in self.finalizable_statuses:
            raise ProposalDraftNotReviewableError(
                f"proposal draft {draft.id} cannot be {action} from "
                f"status {draft.status.value!r}"
            )
        if draft.review is not None:
            raise ProposalDraftNotReviewableError(
                f"proposal draft {draft.id} already has a final review"
            )
        return draft

    @staticmethod
    def _parse_observation(draft: ProposalDraft) -> ProposalObservation:
        try:
            return ProposalObservation.model_validate(draft.proposed_data)
        except ValidationError as exc:
            raise ProposalReviewConflictError(
                f"proposal draft {draft.id} contains invalid proposed data: {exc}"
            ) from exc

    @staticmethod
    def _validate_baseline(
        draft: ProposalDraft,
        proposal: Proposal,
        latest: ProposalStatusEvent | None,
    ) -> None:
        latest_id = latest.id if latest else None
        if draft.kind is ProposalDraftKind.INITIAL:
            if proposal.published_at is not None or latest_id is not None:
                raise ProposalDraftStaleError(
                    f"initial proposal draft {draft.id} is stale"
                )
            return
        if proposal.published_at is None:
            raise ProposalDraftStaleError(
                f"proposal update draft {draft.id} has no published baseline"
            )
        if draft.baseline_status_event_id != latest_id:
            raise ProposalDraftStaleError(
                f"proposal draft {draft.id} is stale: expected status event "
                f"{draft.baseline_status_event_id}, found {latest_id}"
            )

    @staticmethod
    def _publish_actors(
        session: Session, proposal: Proposal, observation: ProposalObservation
    ) -> None:
        resolved = observation.metadata.get("_resolved_actors", [])
        if not isinstance(resolved, list):
            raise ProposalReviewConflictError("resolved actor metadata is invalid")
        for actor in resolved:
            if not isinstance(actor, dict):
                raise ProposalReviewConflictError("resolved actor metadata is invalid")
            actor_type = ProposalActorType(actor["actor_type"])
            role = ProposalActorRole(actor["role"])
            identity_key = ProposalService.actor_identity(
                actor_type=actor_type.value,
                role=role.value,
                politician_id=actor.get("politician_id"),
                political_party_id=actor.get("political_party_id"),
                institution_name=actor.get("institution_name"),
                source_actor_identifier=actor.get("source_actor_identifier"),
            )
            existing = session.scalar(
                select(ProposalActor).where(
                    ProposalActor.proposal_id == proposal.id,
                    ProposalActor.identity_key == identity_key,
                )
            )
            if existing is None:
                session.add(
                    ProposalActor(
                        proposal_id=proposal.id,
                        actor_type=actor_type,
                        role=role,
                        politician_id=actor.get("politician_id"),
                        political_party_id=actor.get("political_party_id"),
                        institution_name=actor.get("institution_name"),
                        display_name=actor["display_name"],
                        source_actor_identifier=actor.get("source_actor_identifier"),
                        identity_key=identity_key,
                    )
                )

    @staticmethod
    def _publish_status_event(
        session: Session,
        *,
        proposal: Proposal,
        draft: ProposalDraft,
        source: Source,
        observation: ProposalObservation,
    ) -> ProposalStatusEvent | None:
        identity_key = ProposalService.status_event_identity(observation)
        existing = session.scalar(
            select(ProposalStatusEvent).where(
                ProposalStatusEvent.proposal_id == proposal.id,
                ProposalStatusEvent.identity_key == identity_key,
            )
        )
        if existing is not None:
            if draft.kind is ProposalDraftKind.STATUS_UPDATE:
                raise ProposalReviewConflictError(
                    "status-update draft would duplicate a published status event"
                )
            return None
        event = ProposalStatusEvent(
            proposal_id=proposal.id,
            normalized_status=observation.normalized_status,
            source_status_label=observation.source_status_label,
            effective_at=observation.status_effective_at,
            observed_at=observation.observed_at,
            source_id=source.id,
            raw_document_id=draft.raw_document_id,
            source_url=str(observation.status_url or observation.official_url),
            source_field=observation.source_field,
            identity_key=identity_key,
        )
        session.add(event)
        session.flush()
        return event
