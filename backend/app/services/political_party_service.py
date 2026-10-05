from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    PoliticalParty,
    PoliticalPartyAffiliation,
    PoliticalPartySourceIdentifier,
    PoliticianSourceIdentifier,
    RawDocument,
    Source,
)
from backend.app.schemas import (
    PartyAffiliationOverlapWarning,
    PartyAffiliationPersistenceDetail,
    PartyAffiliationPersistenceStatus,
    PoliticalPartyObservation,
    PoliticalPartySyncResult,
)


class PoliticalPartyServiceError(RuntimeError):
    """Base class for controlled political-party persistence failures."""


class PoliticalPartyValidationError(PoliticalPartyServiceError):
    pass


class PoliticalPartyConflictError(PoliticalPartyServiceError):
    pass


class PoliticalPartyPersistenceError(PoliticalPartyServiceError):
    pass


class PoliticalPartyService:
    """Persist only explicit party observations for already-resolved people."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(
        self, observations: tuple[PoliticalPartyObservation, ...]
    ) -> PoliticalPartySyncResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    result = self._sync_in_session(session, observations)
            return result
        except (PoliticalPartyValidationError, PoliticalPartyConflictError):
            raise
        except IntegrityError as exc:
            raise PoliticalPartyConflictError(
                "political-party persistence conflicted with another write; "
                "transaction rolled back"
            ) from exc
        except Exception as exc:
            raise PoliticalPartyPersistenceError(
                "political-party persistence failed; transaction rolled back: "
                f"{exc}"
            ) from exc

    def _sync_in_session(
        self,
        session: Session,
        observations: tuple[PoliticalPartyObservation, ...],
    ) -> PoliticalPartySyncResult:
        details: list[PartyAffiliationPersistenceDetail] = []
        parties_created = 0
        created = 0
        updated = 0
        unchanged = 0
        unresolved = 0
        affected_politicians: set[int] = set()

        for observation in observations:
            source = self._validate_observation(session, observation)
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
                        PartyAffiliationPersistenceStatus.UNRESOLVED_POLITICIAN,
                    )
                )
                continue

            politician_id = politician_ids[0]
            party, was_created = self._get_or_create_party(
                session, source, observation
            )
            parties_created += int(was_created)
            status = self._upsert_affiliation(
                session,
                source=source,
                politician_id=politician_id,
                party=party,
                observation=observation,
            )
            if status is PartyAffiliationPersistenceStatus.CREATED:
                created += 1
            elif status is PartyAffiliationPersistenceStatus.UPDATED:
                updated += 1
            else:
                unchanged += 1
            affected_politicians.add(politician_id)
            details.append(self._detail(observation, status, politician_id))

        session.flush()
        return PoliticalPartySyncResult(
            total_observations=len(observations),
            parties_created=parties_created,
            affiliations_created=created,
            affiliations_updated=updated,
            affiliations_unchanged=unchanged,
            unresolved_references=unresolved,
            details=tuple(details),
            overlap_warnings=self._overlap_warnings(
                session, affected_politicians
            ),
        )

    @staticmethod
    def _validate_observation(
        session: Session, observation: PoliticalPartyObservation
    ) -> Source:
        if (
            observation.affiliation_start is not None
            and observation.affiliation_end is not None
            and observation.affiliation_end < observation.affiliation_start
        ):
            raise PoliticalPartyValidationError(
                "affiliation end date cannot be before start date"
            )
        if (
            observation.party_active_from is not None
            and observation.party_active_until is not None
            and observation.party_active_until < observation.party_active_from
        ):
            raise PoliticalPartyValidationError(
                "party active-until date cannot be before active-from date"
            )
        document = session.get(RawDocument, observation.raw_document_id)
        if document is None:
            raise PoliticalPartyValidationError(
                f"RawDocument {observation.raw_document_id} does not exist"
            )
        source = session.scalar(
            select(Source).where(Source.key == observation.source_key)
        )
        if source is None:
            raise PoliticalPartyValidationError(
                f"unknown source {observation.source_key!r}"
            )
        if document.source_id != source.id:
            raise PoliticalPartyValidationError(
                "party observation source does not match its RawDocument"
            )
        return source

    @staticmethod
    def _get_or_create_party(
        session: Session,
        source: Source,
        observation: PoliticalPartyObservation,
    ) -> tuple[PoliticalParty, bool]:
        identifier = session.scalar(
            select(PoliticalPartySourceIdentifier).where(
                PoliticalPartySourceIdentifier.source_id == source.id,
                PoliticalPartySourceIdentifier.value
                == observation.party_source_identifier,
            )
        )
        if identifier is not None:
            party = identifier.political_party
            if party.country != observation.country:
                raise PoliticalPartyConflictError(
                    "official party identifier points to a different country"
                )
            if (
                observation.party_active_from is not None
                and party.active_from not in (None, observation.party_active_from)
            ):
                raise PoliticalPartyConflictError(
                    "official party identifier has a conflicting active-from date"
                )
            resulting_active_from = observation.party_active_from or party.active_from
            resulting_active_until = (
                observation.party_active_until or party.active_until
            )
            if (
                resulting_active_from is not None
                and resulting_active_until is not None
                and resulting_active_until < resulting_active_from
            ):
                raise PoliticalPartyConflictError(
                    "official party identifier has conflicting active dates"
                )
            party.canonical_name = observation.party_name
            party.abbreviation = observation.abbreviation
            if observation.official_website_url is not None:
                party.official_website_url = str(observation.official_website_url)
            if observation.party_active_from is not None:
                party.active_from = observation.party_active_from
            if observation.party_active_until is not None:
                party.active_until = observation.party_active_until
            return party, False

        party = PoliticalParty(
            canonical_name=observation.party_name,
            abbreviation=observation.abbreviation,
            official_website_url=(
                str(observation.official_website_url)
                if observation.official_website_url is not None
                else None
            ),
            country=observation.country,
            active_from=observation.party_active_from,
            active_until=observation.party_active_until,
        )
        session.add(party)
        session.flush()
        session.add(
            PoliticalPartySourceIdentifier(
                political_party_id=party.id,
                source_id=source.id,
                value=observation.party_source_identifier,
            )
        )
        return party, True

    def _upsert_affiliation(
        self,
        session: Session,
        *,
        source: Source,
        politician_id: int,
        party: PoliticalParty,
        observation: PoliticalPartyObservation,
    ) -> PartyAffiliationPersistenceStatus:
        identity_key = self.affiliation_identity_key(observation)
        affiliation = session.scalar(
            select(PoliticalPartyAffiliation).where(
                PoliticalPartyAffiliation.source_id == source.id,
                PoliticalPartyAffiliation.identity_key == identity_key,
            )
        )
        if affiliation is None:
            session.add(
                PoliticalPartyAffiliation(
                    politician_id=politician_id,
                    political_party_id=party.id,
                    source_id=source.id,
                    raw_document_id=observation.raw_document_id,
                    identity_key=identity_key,
                    source_identifier=observation.affiliation_source_identifier,
                    source_url=str(observation.source_url),
                    source_field=observation.source_field,
                    start_date=observation.affiliation_start,
                    end_date=observation.affiliation_end,
                    affiliation_type=observation.affiliation_type,
                )
            )
            return PartyAffiliationPersistenceStatus.CREATED

        if (
            affiliation.politician_id != politician_id
            or affiliation.political_party_id != party.id
            or affiliation.start_date != observation.affiliation_start
            or affiliation.affiliation_type != observation.affiliation_type
            or affiliation.source_field != observation.source_field
        ):
            raise PoliticalPartyConflictError(
                "affiliation identity key resolves to conflicting source data"
            )

        changed = False
        if (
            observation.affiliation_end is not None
            and affiliation.end_date != observation.affiliation_end
        ):
            affiliation.end_date = observation.affiliation_end
            changed = True
        if (
            observation.affiliation_source_identifier is not None
            and affiliation.source_identifier
            != observation.affiliation_source_identifier
        ):
            if affiliation.source_identifier is not None:
                raise PoliticalPartyConflictError(
                    "official affiliation identifier changed for an existing record"
                )
            affiliation.source_identifier = observation.affiliation_source_identifier
            changed = True
        affiliation.raw_document_id = observation.raw_document_id
        affiliation.source_url = str(observation.source_url)
        return (
            PartyAffiliationPersistenceStatus.UPDATED
            if changed
            else PartyAffiliationPersistenceStatus.ALREADY_EXISTS
        )

    @staticmethod
    def affiliation_identity_key(observation: PoliticalPartyObservation) -> str:
        canonical = json.dumps(
            [
                observation.affiliation_source_identifier,
                observation.politician_source_identifier,
                observation.party_source_identifier,
                observation.affiliation_start.isoformat()
                if observation.affiliation_start is not None
                else None,
                observation.affiliation_type,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _detail(
        observation: PoliticalPartyObservation,
        status: PartyAffiliationPersistenceStatus,
        politician_id: int | None = None,
    ) -> PartyAffiliationPersistenceDetail:
        return PartyAffiliationPersistenceDetail(
            status=status,
            politician_id=politician_id,
            politician_source_identifier=observation.politician_source_identifier,
            party_name=observation.party_name,
            party_source_identifier=observation.party_source_identifier,
            start_date=observation.affiliation_start,
            end_date=observation.affiliation_end,
            affiliation_type=observation.affiliation_type,
        )

    @staticmethod
    def _overlap_warnings(
        session: Session, politician_ids: set[int]
    ) -> tuple[PartyAffiliationOverlapWarning, ...]:
        if not politician_ids:
            return ()
        affiliations = list(
            session.scalars(
                select(PoliticalPartyAffiliation)
                .where(PoliticalPartyAffiliation.politician_id.in_(politician_ids))
                .order_by(
                    PoliticalPartyAffiliation.politician_id,
                    PoliticalPartyAffiliation.start_date,
                    PoliticalPartyAffiliation.id,
                )
            )
        )
        warnings: list[PartyAffiliationOverlapWarning] = []
        for index, left in enumerate(affiliations):
            if left.start_date is None:
                continue
            for right in affiliations[index + 1 :]:
                if right.politician_id != left.politician_id:
                    break
                if right.start_date is None:
                    continue
                if left.end_date is None or right.start_date <= left.end_date:
                    warnings.append(
                        PartyAffiliationOverlapWarning(
                            politician_id=left.politician_id,
                            affiliation_ids=(left.id, right.id),
                        )
                    )
        return tuple(warnings)
