import json
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    PoliticalPartySourceIdentifier,
    PoliticianSourceIdentifier,
    Proposal,
    ProposalActorRole,
    ProposalDraft,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalEvidence,
    ProposalSourceIdentifier,
    ProposalStatusEvent,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.schemas import (
    ObservedActorType,
    ProposalObservation,
    ProposalSyncDetail,
    ProposalSyncDisposition,
    ProposalSyncResult,
)


class ProposalServiceError(RuntimeError):
    pass


class ProposalValidationError(ProposalServiceError):
    pass


class ProposalConflictError(ProposalServiceError):
    pass


class ProposalPersistenceError(ProposalServiceError):
    pass


class ProposalService:
    """Create internal proposal drafts from deterministic source observations."""

    active_draft_statuses = (
        ProposalDraftStatus.PENDING,
        ProposalDraftStatus.IN_REVIEW,
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(self, observations: tuple[ProposalObservation, ...]) -> ProposalSyncResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    result = self._sync_in_session(session, observations)
            return result
        except (ProposalValidationError, ProposalConflictError):
            raise
        except IntegrityError as exc:
            raise ProposalConflictError(
                "proposal persistence conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise ProposalPersistenceError(
                f"proposal persistence failed; transaction rolled back: {exc}"
            ) from exc

    def _sync_in_session(
        self,
        session: Session,
        observations: tuple[ProposalObservation, ...],
    ) -> ProposalSyncResult:
        created_proposals = created_drafts = unchanged = 0
        resolved_actor_count = unresolved_actor_count = 0
        details: list[ProposalSyncDetail] = []

        for observation in observations:
            source, document = self._validate_observation(session, observation)
            proposal, proposal_created = self._get_or_create_proposal(
                session, source, observation
            )
            created_proposals += int(proposal_created)
            resolved, unresolved = self._resolve_actors(session, observation)
            resolved_actor_count += len(resolved)
            unresolved_actor_count += len(unresolved)
            if not observation.actors:
                unresolved = ("official source supplied no actor",)
                unresolved_actor_count += 1
            self._validate_evidence(observation)
            self._validate_chronology(session, proposal, observation)

            observation_hash = self.observation_hash(observation)
            existing = session.scalar(
                select(ProposalDraft).where(
                    ProposalDraft.proposal_id == proposal.id,
                    ProposalDraft.observation_hash == observation_hash,
                )
            )
            if existing is not None:
                unchanged += 1
                details.append(
                    ProposalSyncDetail(
                        proposal_id=proposal.id,
                        draft_id=existing.id,
                        proposal_identifier=observation.proposal_identifier,
                        title=observation.title,
                        disposition=ProposalSyncDisposition.ALREADY_OBSERVED,
                        unresolved_actors=unresolved,
                    )
                )
                continue

            baseline = self._latest_status_event(session, proposal.id)
            if proposal.published_at is None:
                kind = ProposalDraftKind.INITIAL
            elif baseline is None or (
                baseline.identity_key != self.status_event_identity(observation)
            ):
                kind = ProposalDraftKind.STATUS_UPDATE
            else:
                kind = ProposalDraftKind.METADATA_UPDATE

            active_drafts = list(
                session.scalars(
                    select(ProposalDraft)
                    .where(
                        ProposalDraft.proposal_id == proposal.id,
                        ProposalDraft.status.in_(self.active_draft_statuses),
                    )
                    .order_by(ProposalDraft.created_at.desc(), ProposalDraft.id.desc())
                    .with_for_update()
                )
            )
            for active in active_drafts:
                active.status = ProposalDraftStatus.SUPERSEDED

            payload = observation.model_dump(mode="json")
            payload["metadata"] = {
                **payload.get("metadata", {}),
                "_resolved_actors": resolved,
                "_unresolved_actors": list(unresolved),
            }
            draft = ProposalDraft(
                proposal_id=proposal.id,
                raw_document_id=document.id,
                baseline_status_event_id=baseline.id if baseline else None,
                supersedes_id=active_drafts[0].id if active_drafts else None,
                kind=kind,
                status=ProposalDraftStatus.PENDING,
                observation_hash=observation_hash,
                proposed_data=payload,
            )
            session.add(draft)
            session.flush()
            session.add_all(
                ProposalEvidence(
                    draft_id=draft.id,
                    source_id=source.id,
                    raw_document_id=document.id,
                    field_path=item.field_path,
                    source_url=str(item.source_url),
                    source_field=item.source_field,
                    source_value=item.source_value,
                    observed_at=observation.observed_at,
                )
                for item in observation.evidence
            )
            session.flush()
            created_drafts += 1
            details.append(
                ProposalSyncDetail(
                    proposal_id=proposal.id,
                    draft_id=draft.id,
                    proposal_identifier=observation.proposal_identifier,
                    title=observation.title,
                    disposition=ProposalSyncDisposition.DRAFT_CREATED,
                    unresolved_actors=unresolved,
                )
            )

        return ProposalSyncResult(
            total_observations=len(observations),
            proposals_created=created_proposals,
            drafts_created=created_drafts,
            unchanged=unchanged,
            resolved_actors=resolved_actor_count,
            unresolved_actors=unresolved_actor_count,
            details=tuple(details),
        )

    @staticmethod
    def _validate_observation(
        session: Session, observation: ProposalObservation
    ) -> tuple[Source, RawDocument]:
        source = session.scalar(select(Source).where(Source.key == observation.source_key))
        if source is None:
            raise ProposalValidationError(
                f"unknown proposal source {observation.source_key!r}"
            )
        document = session.get(RawDocument, observation.raw_document_id)
        if document is None:
            raise ProposalValidationError(
                f"RawDocument {observation.raw_document_id} does not exist"
            )
        if document.source_id != source.id:
            raise ProposalValidationError(
                "proposal observation source does not match its RawDocument"
            )
        if document.process_status is not RawDocumentStatus.PARSED:
            raise ProposalValidationError("proposal RawDocument is not successfully parsed")
        return source, document

    @staticmethod
    def _get_or_create_proposal(
        session: Session, source: Source, observation: ProposalObservation
    ) -> tuple[Proposal, bool]:
        identifier = session.scalar(
            select(ProposalSourceIdentifier).where(
                ProposalSourceIdentifier.source_id == source.id,
                ProposalSourceIdentifier.official_identifier
                == observation.proposal_identifier,
            )
        )
        if identifier is not None:
            return identifier.proposal, False
        proposal = Proposal(
            canonical_title=observation.title,
            summary=observation.summary,
            exact_statement=observation.exact_statement,
            proposal_type=observation.proposal_type,
            introduced_at=observation.introduced_at,
        )
        session.add(proposal)
        session.flush()
        session.add(
            ProposalSourceIdentifier(
                proposal_id=proposal.id,
                source_id=source.id,
                official_identifier=observation.proposal_identifier,
                source_url=str(observation.official_url),
            )
        )
        session.flush()
        return proposal, True

    @staticmethod
    def _resolve_actors(
        session: Session, observation: ProposalObservation
    ) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
        resolved: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for actor in observation.actors:
            target: dict[str, Any] = {
                "actor_type": actor.actor_type.value,
                "role": actor.role.value,
                "display_name": actor.display_name,
                "source_actor_identifier": actor.source_identifier,
                "institution_name": actor.institution_name,
                "politician_id": None,
                "political_party_id": None,
            }
            if actor.actor_type is ObservedActorType.INSTITUTION:
                resolved.append(target)
                continue
            if actor.actor_type is ObservedActorType.UNRESOLVED:
                unresolved.append(actor.display_name)
                continue
            authority = session.scalar(
                select(Source).where(Source.key == actor.authority_key)
            )
            if authority is None:
                unresolved.append(actor.display_name)
                continue
            if actor.actor_type is ObservedActorType.POLITICIAN:
                identifiers = tuple(
                    session.scalars(
                        select(PoliticianSourceIdentifier).where(
                            PoliticianSourceIdentifier.source_id == authority.id,
                            PoliticianSourceIdentifier.value == actor.source_identifier,
                        )
                    )
                )
                if len(identifiers) == 1:
                    target["politician_id"] = identifiers[0].politician_id
                    resolved.append(target)
                else:
                    unresolved.append(actor.display_name)
            else:
                identifiers = tuple(
                    session.scalars(
                        select(PoliticalPartySourceIdentifier).where(
                            PoliticalPartySourceIdentifier.source_id == authority.id,
                            PoliticalPartySourceIdentifier.value
                            == actor.source_identifier,
                        )
                    )
                )
                if len(identifiers) == 1:
                    target["political_party_id"] = identifiers[0].political_party_id
                    resolved.append(target)
                else:
                    unresolved.append(actor.display_name)
        return resolved, tuple(unresolved)

    @staticmethod
    def _validate_evidence(observation: ProposalObservation) -> None:
        paths = {item.field_path for item in observation.evidence}
        required = {"title", "proposal_type", "current_status"}
        if observation.introduced_at is not None:
            required.add("introduced_at")
        if observation.proposal_type.value == "explicit_promise":
            required.add("exact_statement")
        missing = sorted(required - paths)
        if missing:
            raise ProposalValidationError(
                "proposal observation lacks evidence for: " + ", ".join(missing)
            )

    @classmethod
    def _validate_chronology(
        cls, session: Session, proposal: Proposal, observation: ProposalObservation
    ) -> None:
        latest = cls._latest_status_event(session, proposal.id)
        if (
            latest is not None
            and latest.identity_key != cls.status_event_identity(observation)
            and latest.effective_at is not None
            and observation.status_effective_at is not None
            and observation.status_effective_at < latest.effective_at
        ):
            raise ProposalValidationError(
                "proposal status observation predates the latest published status event"
            )

    @staticmethod
    def _latest_status_event(
        session: Session, proposal_id: int
    ) -> ProposalStatusEvent | None:
        return session.scalar(
            select(ProposalStatusEvent)
            .where(ProposalStatusEvent.proposal_id == proposal_id)
            .order_by(
                ProposalStatusEvent.effective_at.desc(),
                ProposalStatusEvent.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def observation_hash(observation: ProposalObservation) -> str:
        payload = observation.model_dump(mode="json")
        payload.pop("raw_document_id", None)
        payload.pop("observed_at", None)
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def status_event_identity(observation: ProposalObservation) -> str:
        canonical = json.dumps(
            [
                observation.status_source_identifier,
                observation.normalized_status.value,
                observation.source_status_label,
                observation.status_effective_at.isoformat()
                if observation.status_effective_at
                else None,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def actor_identity(
        *,
        actor_type: str,
        role: str,
        politician_id: int | None,
        political_party_id: int | None,
        institution_name: str | None,
        source_actor_identifier: str | None,
    ) -> str:
        canonical = json.dumps(
            [
                actor_type,
                role,
                politician_id,
                political_party_id,
                institution_name,
                source_actor_identifier,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()
