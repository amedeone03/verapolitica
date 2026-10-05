from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    ParliamentaryGroupSourceIdentifier,
    PoliticianSourceIdentifier,
    RawDocument,
    Source,
)
from backend.app.schemas import (
    MembershipOverlapWarning,
    MembershipPersistenceDetail,
    MembershipPersistenceStatus,
    ParliamentaryGroupObservation,
    ParliamentaryGroupSyncResult,
)


class ParliamentaryGroupServiceError(RuntimeError):
    """Base class for controlled parliamentary-group persistence failures."""


class ParliamentaryGroupValidationError(ParliamentaryGroupServiceError):
    pass


class ParliamentaryGroupConflictError(ParliamentaryGroupServiceError):
    pass


class ParliamentaryGroupPersistenceError(ParliamentaryGroupServiceError):
    pass


class ParliamentaryGroupService:
    """Persist mapped group observations without performing identity matching."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(
        self, observations: tuple[ParliamentaryGroupObservation, ...]
    ) -> ParliamentaryGroupSyncResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    result = self._sync_in_session(session, observations)
            return result
        except (ParliamentaryGroupValidationError, ParliamentaryGroupConflictError):
            raise
        except IntegrityError as exc:
            raise ParliamentaryGroupConflictError(
                "parliamentary-group persistence conflicted with another write; "
                "transaction rolled back"
            ) from exc
        except Exception as exc:
            raise ParliamentaryGroupPersistenceError(
                "parliamentary-group persistence failed; transaction rolled back: "
                f"{exc}"
            ) from exc

    def _sync_in_session(
        self,
        session: Session,
        observations: tuple[ParliamentaryGroupObservation, ...],
    ) -> ParliamentaryGroupSyncResult:
        details: list[MembershipPersistenceDetail] = []
        groups_created = 0
        created = 0
        updated = 0
        unchanged = 0
        unresolved = 0
        affected_politicians: set[int] = set()

        for observation in observations:
            self._validate_observation(session, observation)
            source = session.scalar(
                select(Source).where(Source.key == observation.source_key)
            )
            if source is None:  # narrowed by _validate_observation
                raise ParliamentaryGroupValidationError(
                    f"unknown source {observation.source_key!r}"
                )
            politician_ids = tuple(
                session.scalars(
                    select(PoliticianSourceIdentifier.politician_id).where(
                        PoliticianSourceIdentifier.source_id == source.id,
                        PoliticianSourceIdentifier.value
                        == observation.politician_source_identifier,
                    )
                )
            )
            if len(politician_ids) != 1:
                unresolved += 1
                details.append(
                    self._detail(
                        observation,
                        MembershipPersistenceStatus.UNRESOLVED_POLITICIAN,
                    )
                )
                continue
            politician_id = politician_ids[0]

            group, was_created = self._get_or_create_group(
                session, source, observation
            )
            groups_created += int(was_created)
            status = self._upsert_membership(
                session,
                source=source,
                politician_id=politician_id,
                group=group,
                observation=observation,
            )
            if status is MembershipPersistenceStatus.CREATED:
                created += 1
            elif status is MembershipPersistenceStatus.UPDATED:
                updated += 1
            else:
                unchanged += 1
            affected_politicians.add(politician_id)
            details.append(self._detail(observation, status, politician_id))

        session.flush()
        warnings = self._overlap_warnings(session, affected_politicians)
        return ParliamentaryGroupSyncResult(
            total_observations=len(observations),
            groups_created=groups_created,
            memberships_created=created,
            memberships_updated=updated,
            memberships_unchanged=unchanged,
            unresolved_references=unresolved,
            details=tuple(details),
            overlap_warnings=warnings,
        )

    @staticmethod
    def _validate_observation(
        session: Session, observation: ParliamentaryGroupObservation
    ) -> None:
        if (
            observation.start_date is not None
            and observation.end_date is not None
            and observation.end_date < observation.start_date
        ):
            raise ParliamentaryGroupValidationError(
                "membership end_date cannot be before start_date"
            )
        document = session.get(RawDocument, observation.raw_document_id)
        if document is None:
            raise ParliamentaryGroupValidationError(
                f"RawDocument {observation.raw_document_id} does not exist"
            )
        source = session.scalar(
            select(Source).where(Source.key == observation.source_key)
        )
        if source is None:
            raise ParliamentaryGroupValidationError(
                f"unknown source {observation.source_key!r}"
            )
        if document.source_id != source.id:
            raise ParliamentaryGroupValidationError(
                "group observation source does not match its RawDocument"
            )

    @staticmethod
    def _get_or_create_group(
        session: Session,
        source: Source,
        observation: ParliamentaryGroupObservation,
    ) -> tuple[ParliamentaryGroup, bool]:
        identifier = session.scalar(
            select(ParliamentaryGroupSourceIdentifier).where(
                ParliamentaryGroupSourceIdentifier.source_id == source.id,
                ParliamentaryGroupSourceIdentifier.value
                == observation.group_source_identifier,
                ParliamentaryGroupSourceIdentifier.legislature
                == observation.legislature,
            )
        )
        if identifier is not None:
            group = identifier.parliamentary_group
            if (
                group.institution != observation.institution
                or group.legislature != observation.legislature
            ):
                raise ParliamentaryGroupConflictError(
                    "official group identifier points to a different institutional scope"
                )
            group.canonical_name = observation.canonical_name
            group.abbreviation = observation.abbreviation
            return group, False

        group = ParliamentaryGroup(
            canonical_name=observation.canonical_name,
            abbreviation=observation.abbreviation,
            institution=observation.institution,
            legislature=observation.legislature,
        )
        session.add(group)
        session.flush()
        session.add(
            ParliamentaryGroupSourceIdentifier(
                parliamentary_group_id=group.id,
                source_id=source.id,
                value=observation.group_source_identifier,
                legislature=observation.legislature,
            )
        )
        return group, True

    def _upsert_membership(
        self,
        session: Session,
        *,
        source: Source,
        politician_id: int,
        group: ParliamentaryGroup,
        observation: ParliamentaryGroupObservation,
    ) -> MembershipPersistenceStatus:
        identity_key = self.membership_identity_key(observation)
        membership = session.scalar(
            select(ParliamentaryGroupMembership).where(
                ParliamentaryGroupMembership.source_id == source.id,
                ParliamentaryGroupMembership.identity_key == identity_key,
            )
        )
        if membership is None:
            session.add(
                ParliamentaryGroupMembership(
                    politician_id=politician_id,
                    parliamentary_group_id=group.id,
                    source_id=source.id,
                    raw_document_id=observation.raw_document_id,
                    identity_key=identity_key,
                    source_identifier=observation.membership_source_identifier,
                    source_url=str(observation.source_url),
                    start_date=observation.start_date,
                    end_date=observation.end_date,
                    role=observation.role,
                )
            )
            return MembershipPersistenceStatus.CREATED

        if (
            membership.politician_id != politician_id
            or membership.parliamentary_group_id != group.id
            or membership.start_date != observation.start_date
            or membership.role != observation.role
        ):
            raise ParliamentaryGroupConflictError(
                "membership identity key resolves to conflicting source data"
            )

        changed = False
        if observation.end_date is not None and membership.end_date != observation.end_date:
            membership.end_date = observation.end_date
            changed = True
        if (
            observation.membership_source_identifier is not None
            and membership.source_identifier
            != observation.membership_source_identifier
        ):
            if membership.source_identifier is not None:
                raise ParliamentaryGroupConflictError(
                    "membership official identifier changed for an existing record"
                )
            membership.source_identifier = observation.membership_source_identifier
            changed = True
        membership.raw_document_id = observation.raw_document_id
        membership.source_url = str(observation.source_url)
        return (
            MembershipPersistenceStatus.UPDATED
            if changed
            else MembershipPersistenceStatus.ALREADY_EXISTS
        )

    @staticmethod
    def membership_identity_key(
        observation: ParliamentaryGroupObservation,
    ) -> str:
        canonical = json.dumps(
            [
                observation.membership_source_identifier,
                observation.politician_source_identifier,
                observation.group_source_identifier,
                observation.legislature,
                observation.start_date.isoformat()
                if observation.start_date is not None
                else None,
                observation.role,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _detail(
        observation: ParliamentaryGroupObservation,
        status: MembershipPersistenceStatus,
        politician_id: int | None = None,
    ) -> MembershipPersistenceDetail:
        return MembershipPersistenceDetail(
            status=status,
            politician_id=politician_id,
            politician_source_identifier=observation.politician_source_identifier,
            group_name=observation.canonical_name,
            group_source_identifier=observation.group_source_identifier,
            start_date=observation.start_date,
            end_date=observation.end_date,
            role=observation.role,
        )

    @staticmethod
    def _overlap_warnings(
        session: Session, politician_ids: set[int]
    ) -> tuple[MembershipOverlapWarning, ...]:
        if not politician_ids:
            return ()
        memberships = list(
            session.scalars(
                select(ParliamentaryGroupMembership)
                .join(ParliamentaryGroup)
                .where(ParliamentaryGroupMembership.politician_id.in_(politician_ids))
                .order_by(
                    ParliamentaryGroupMembership.politician_id,
                    ParliamentaryGroup.institution,
                    ParliamentaryGroup.legislature,
                    ParliamentaryGroupMembership.start_date,
                    ParliamentaryGroupMembership.id,
                )
            )
        )
        warnings: list[MembershipOverlapWarning] = []
        for index, left in enumerate(memberships):
            if left.start_date is None:
                continue
            left_group = left.parliamentary_group
            for right in memberships[index + 1 :]:
                right_group = right.parliamentary_group
                if right.politician_id != left.politician_id:
                    break
                if (
                    right_group.institution != left_group.institution
                    or right_group.legislature != left_group.legislature
                    or right.start_date is None
                ):
                    continue
                if left.end_date is None or right.start_date <= left.end_date:
                    warnings.append(
                        MembershipOverlapWarning(
                            politician_id=left.politician_id,
                            institution=left_group.institution,
                            legislature=left_group.legislature,
                            membership_ids=(left.id, right.id),
                        )
                    )
        return tuple(warnings)
