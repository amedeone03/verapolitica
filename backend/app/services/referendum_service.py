from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Municipality,
    RawDocument,
    Region,
    Source,
)
from backend.app.models.civic import (
    GeographicScopeType,
    Referendum,
    ReferendumDraft,
    ReferendumDraftKind,
    ReferendumDraftStatus,
    ReferendumEvidence,
    ReferendumSourceIdentifier,
)
from backend.app.schemas.civic import (
    ReferendumObservation,
    ReferendumSyncDetail,
    ReferendumSyncDisposition,
    ReferendumSyncResult,
)


class ReferendumServiceError(RuntimeError):
    pass


class ReferendumValidationError(ReferendumServiceError):
    pass


class ReferendumConflictError(ReferendumServiceError):
    pass


class ReferendumPersistenceError(ReferendumServiceError):
    pass


ACTIVE_DRAFT_STATUSES = (
    ReferendumDraftStatus.PENDING,
    ReferendumDraftStatus.IN_REVIEW,
)


class ReferendumService:
    """Ingest official referendum observations as unpublished drafts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(
        self, observations: tuple[ReferendumObservation, ...]
    ) -> ReferendumSyncResult:
        details: list[ReferendumSyncDetail] = []
        created = 0
        already_observed = 0
        try:
            with self.session_factory() as session:
                with session.begin():
                    for observation in observations:
                        detail = self._sync_one(session, observation)
                        details.append(detail)
                        if detail.disposition is ReferendumSyncDisposition.DRAFT_CREATED:
                            created += 1
                        else:
                            already_observed += 1
        except ReferendumServiceError:
            raise
        except Exception as exc:
            raise ReferendumPersistenceError(
                f"referendum sync failed; transaction rolled back: {exc}"
            ) from exc
        return ReferendumSyncResult(
            details=tuple(details),
            created=created,
            already_observed=already_observed,
        )

    def _sync_one(
        self, session: Session, observation: ReferendumObservation
    ) -> ReferendumSyncDetail:
        source = session.scalar(select(Source).where(Source.key == observation.source_key))
        if source is None:
            raise ReferendumValidationError(
                f"unknown referendum source {observation.source_key!r}"
            )
        document = session.scalar(
            select(RawDocument).where(RawDocument.id == observation.raw_document_id)
        )
        if document is None or document.source_id != source.id:
            raise ReferendumValidationError(
                "referendum observation must point at a parsed document from the same source"
            )
        region, municipality = self._resolve_scope(session, observation)
        digest = self.observation_hash(observation)
        identifier = session.scalar(
            select(ReferendumSourceIdentifier).where(
                ReferendumSourceIdentifier.source_id == source.id,
                ReferendumSourceIdentifier.official_identifier
                == observation.official_identifier,
            )
        )
        if identifier is None:
            referendum = Referendum(
                title=observation.title,
                official_question=observation.official_question,
                referendum_type=observation.referendum_type,
                status=observation.status,
                vote_date=observation.vote_date,
                vote_end_date=observation.vote_end_date,
                start_time=observation.start_time,
                end_time=observation.end_time,
                voting_hours_description=observation.voting_hours_description,
                scope_type=observation.scope_type,
                region_id=region.id if region else None,
                municipality_id=municipality.id if municipality else None,
                quorum_required=observation.quorum_required,
                quorum_description=observation.quorum_description,
                official_source_url=str(observation.official_source_url),
                is_synthetic=observation.is_synthetic,
            )
            session.add(referendum)
            session.flush()
            identifier = ReferendumSourceIdentifier(
                referendum_id=referendum.id,
                source_id=source.id,
                official_identifier=observation.official_identifier,
                source_url=str(observation.official_source_url),
            )
            session.add(identifier)
            session.flush()
        referendum = session.scalar(
            select(Referendum).where(Referendum.id == identifier.referendum_id)
        )
        if referendum is None:
            raise ReferendumConflictError("referendum identity row is missing")
        existing = session.scalar(
            select(ReferendumDraft).where(
                ReferendumDraft.referendum_id == referendum.id,
                ReferendumDraft.observation_hash == digest,
            )
        )
        if existing is not None:
            return ReferendumSyncDetail(
                referendum_id=referendum.id,
                draft_id=existing.id,
                official_identifier=observation.official_identifier,
                title=observation.title,
                disposition=ReferendumSyncDisposition.ALREADY_OBSERVED,
            )
        for active in session.scalars(
            select(ReferendumDraft).where(
                ReferendumDraft.referendum_id == referendum.id,
                ReferendumDraft.status.in_(ACTIVE_DRAFT_STATUSES),
            )
        ):
            active.status = ReferendumDraftStatus.SUPERSEDED
        kind = (
            ReferendumDraftKind.INITIAL
            if referendum.published_at is None
            else ReferendumDraftKind.UPDATE
        )
        draft = ReferendumDraft(
            referendum_id=referendum.id,
            raw_document_id=document.id,
            kind=kind,
            status=ReferendumDraftStatus.PENDING,
            observation_hash=digest,
            proposed_data=observation.model_dump(mode="json"),
        )
        session.add(draft)
        session.flush()
        for item in observation.evidence:
            session.add(
                ReferendumEvidence(
                    draft_id=draft.id,
                    source_id=source.id,
                    raw_document_id=document.id,
                    field_path=item.field_path,
                    source_url=str(item.source_url),
                    source_field=item.source_field,
                    source_value=item.source_value,
                    observed_at=observation.observed_at,
                )
            )
        session.flush()
        return ReferendumSyncDetail(
            referendum_id=referendum.id,
            draft_id=draft.id,
            official_identifier=observation.official_identifier,
            title=observation.title,
            disposition=ReferendumSyncDisposition.DRAFT_CREATED,
        )

    @staticmethod
    def _resolve_scope(
        session: Session, observation: ReferendumObservation
    ) -> tuple[Region | None, Municipality | None]:
        region = None
        municipality = None
        if observation.region_istat_code:
            region = session.scalar(
                select(Region).where(Region.istat_code == observation.region_istat_code)
            )
            if region is None:
                raise ReferendumValidationError(
                    f"unknown region ISTAT code {observation.region_istat_code!r}"
                )
        if observation.municipality_istat_code:
            municipality = session.scalar(
                select(Municipality).where(
                    Municipality.istat_code == observation.municipality_istat_code
                )
            )
            if municipality is None:
                raise ReferendumValidationError(
                    "unknown municipality ISTAT code "
                    f"{observation.municipality_istat_code!r}"
                )
            if observation.scope_type is GeographicScopeType.MUNICIPALITY:
                region = municipality.region
        return region, municipality

    @staticmethod
    def observation_hash(observation: ReferendumObservation) -> str:
        payload = observation.model_dump(mode="json")
        payload.pop("raw_document_id", None)
        payload.pop("observed_at", None)
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return sha256(canonical.encode("utf-8")).hexdigest()
