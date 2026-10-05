from __future__ import annotations

import json
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Municipality,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    Region,
    Source,
    TerritorialOfficeMandate,
)
from backend.app.schemas import (
    MunicipalityObservation,
    RegionObservation,
    TerritorialMandateObservation,
    TerritorialMandatePersistenceDetail,
    TerritorialMandatePersistenceStatus,
    TerritorialMandateSyncResult,
    TerritorySyncResult,
)
from backend.app.services.matching_service import normalize_person_name


class TerritoryServiceError(RuntimeError):
    pass


class TerritoryValidationError(TerritoryServiceError):
    pass


class TerritoryConflictError(TerritoryServiceError):
    pass


class TerritoryPersistenceError(TerritoryServiceError):
    pass


class TerritoryService:
    """Transactionally upsert ISTAT territories without deleting missing rows."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(
        self,
        regions: tuple[RegionObservation, ...] = (),
        municipalities: tuple[MunicipalityObservation, ...] = (),
    ) -> TerritorySyncResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    region_counts = [0, 0, 0]
                    municipality_counts = [0, 0, 0]
                    for observation in regions:
                        disposition = self._upsert_region(session, observation)
                        region_counts[disposition] += 1
                    session.flush()
                    for observation in municipalities:
                        disposition = self._upsert_municipality(session, observation)
                        municipality_counts[disposition] += 1
            return TerritorySyncResult(
                regions_created=region_counts[0],
                regions_updated=region_counts[1],
                regions_unchanged=region_counts[2],
                municipalities_created=municipality_counts[0],
                municipalities_updated=municipality_counts[1],
                municipalities_unchanged=municipality_counts[2],
            )
        except (TerritoryValidationError, TerritoryConflictError):
            raise
        except IntegrityError as exc:
            raise TerritoryConflictError(
                "territory persistence conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise TerritoryPersistenceError(
                f"territory persistence failed; transaction rolled back: {exc}"
            ) from exc

    def sync_regions(
        self, observations: tuple[RegionObservation, ...]
    ) -> TerritorySyncResult:
        return self.sync(regions=observations)

    def sync_municipalities(
        self, observations: tuple[MunicipalityObservation, ...]
    ) -> TerritorySyncResult:
        return self.sync(municipalities=observations)

    @staticmethod
    def _provenance(
        session: Session, observation: RegionObservation | MunicipalityObservation
    ) -> tuple[Source, RawDocument]:
        source = session.scalar(
            select(Source).where(Source.key == observation.source_key)
        )
        if source is None:
            raise TerritoryValidationError(
                f"unknown source {observation.source_key!r}"
            )
        document = session.get(RawDocument, observation.raw_document_id)
        if document is None:
            raise TerritoryValidationError(
                f"RawDocument {observation.raw_document_id} does not exist"
            )
        if document.source_id != source.id:
            raise TerritoryValidationError(
                "territory observation source does not match its RawDocument"
            )
        return source, document

    def _upsert_region(
        self, session: Session, observation: RegionObservation
    ) -> int:
        source, _ = self._provenance(session, observation)
        region = session.scalar(
            select(Region).where(Region.istat_code == observation.istat_code)
        )
        values = {
            "canonical_name": observation.canonical_name.strip(),
            "status": observation.status,
            "active_from": observation.active_from,
            "active_until": observation.active_until,
        }
        provenance = {
            "source_id": source.id,
            "raw_document_id": observation.raw_document_id,
            "source_url": str(observation.source_url),
        }
        if region is None:
            session.add(Region(istat_code=observation.istat_code, **values, **provenance))
            return 0
        changed = any(getattr(region, key) != value for key, value in values.items())
        for key, value in {**values, **provenance}.items():
            setattr(region, key, value)
        return 1 if changed else 2

    def _upsert_municipality(
        self, session: Session, observation: MunicipalityObservation
    ) -> int:
        source, _ = self._provenance(session, observation)
        region = session.scalar(
            select(Region).where(
                Region.istat_code == observation.region_istat_code
            )
        )
        if region is None:
            raise TerritoryValidationError(
                f"unknown region ISTAT code {observation.region_istat_code!r}"
            )
        municipality = session.scalar(
            select(Municipality).where(
                Municipality.istat_code == observation.istat_code
            )
        )
        if municipality is not None and municipality.region_id != region.id:
            raise TerritoryConflictError(
                "municipality ISTAT code cannot move to a different region"
            )
        values = {
            "region_id": region.id,
            "canonical_name": observation.canonical_name.strip(),
            "province_abbreviation": observation.province_abbreviation.upper(),
            "province_name": observation.province_name.strip(),
            "status": observation.status,
            "active_from": observation.active_from,
            "active_until": observation.active_until,
        }
        provenance = {
            "source_id": source.id,
            "raw_document_id": observation.raw_document_id,
            "source_url": str(observation.source_url),
        }
        if municipality is None:
            session.add(Municipality(istat_code=observation.istat_code, **values, **provenance))
            return 0
        changed = any(
            getattr(municipality, key) != value for key, value in values.items()
        )
        for key, value in {**values, **provenance}.items():
            setattr(municipality, key, value)
        return 1 if changed else 2


class TerritorialMandateService:
    """Persist territorial mandates only after conservative exact identity resolution."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync(
        self, observations: tuple[TerritorialMandateObservation, ...]
    ) -> TerritorialMandateSyncResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    result = self._sync_in_session(session, observations)
            return result
        except (TerritoryValidationError, TerritoryConflictError):
            raise
        except IntegrityError as exc:
            raise TerritoryConflictError(
                "mandate persistence conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise TerritoryPersistenceError(
                f"mandate persistence failed; transaction rolled back: {exc}"
            ) from exc

    def _sync_in_session(
        self,
        session: Session,
        observations: tuple[TerritorialMandateObservation, ...],
    ) -> TerritorialMandateSyncResult:
        created = updated = unchanged = unresolved_people = unresolved_territories = 0
        details: list[TerritorialMandatePersistenceDetail] = []
        for observation in observations:
            source = self._validate_provenance(session, observation)
            target = self._target(session, observation)
            if target is None:
                unresolved_territories += 1
                status = TerritorialMandatePersistenceStatus.UNRESOLVED_TERRITORY
                details.append(self._detail(observation, status))
                continue
            politician_id = self._resolve_politician(session, source, observation)
            if politician_id is None:
                unresolved_people += 1
                status = TerritorialMandatePersistenceStatus.UNRESOLVED_POLITICIAN
                details.append(self._detail(observation, status))
                continue
            status = self._upsert(
                session, source, politician_id, target, observation
            )
            created += int(status is TerritorialMandatePersistenceStatus.CREATED)
            updated += int(status is TerritorialMandatePersistenceStatus.UPDATED)
            unchanged += int(
                status is TerritorialMandatePersistenceStatus.ALREADY_EXISTS
            )
            details.append(self._detail(observation, status, politician_id))
        return TerritorialMandateSyncResult(
            total_observations=len(observations),
            mandates_created=created,
            mandates_updated=updated,
            mandates_unchanged=unchanged,
            unresolved_people=unresolved_people,
            unresolved_territories=unresolved_territories,
            details=tuple(details),
        )

    @staticmethod
    def _validate_provenance(
        session: Session, observation: TerritorialMandateObservation
    ) -> Source:
        source = session.scalar(
            select(Source).where(Source.key == observation.source_key)
        )
        document = session.get(RawDocument, observation.raw_document_id)
        if source is None:
            raise TerritoryValidationError(
                f"unknown source {observation.source_key!r}"
            )
        if document is None:
            raise TerritoryValidationError(
                f"RawDocument {observation.raw_document_id} does not exist"
            )
        if document.source_id != source.id:
            raise TerritoryValidationError(
                "mandate observation source does not match its RawDocument"
            )
        return source

    @staticmethod
    def _target(
        session: Session, observation: TerritorialMandateObservation
    ) -> Region | Municipality | None:
        if observation.municipality_istat_code is not None:
            return session.scalar(
                select(Municipality).where(
                    Municipality.istat_code == observation.municipality_istat_code
                )
            )
        return session.scalar(
            select(Region).where(Region.istat_code == observation.region_istat_code)
        )

    @staticmethod
    def _resolve_politician(
        session: Session,
        source: Source,
        observation: TerritorialMandateObservation,
    ) -> int | None:
        if observation.politician_source_identifier is not None:
            ids = tuple(
                session.scalars(
                    select(PoliticianSourceIdentifier.politician_id).where(
                        PoliticianSourceIdentifier.source_id == source.id,
                        PoliticianSourceIdentifier.value
                        == observation.politician_source_identifier,
                    )
                )
            )
            if len(ids) == 1:
                return ids[0]
            if len(ids) > 1:
                return None
        if observation.birth_date is not None:
            normalized = normalize_person_name(
                observation.given_name, observation.family_name
            )
            ids = tuple(
                session.scalars(
                    select(Politician.id).where(
                        Politician.normalized_name == normalized,
                        Politician.birth_date == observation.birth_date,
                    )
                )
            )
        else:
            return None
        return ids[0] if len(ids) == 1 else None

    def _upsert(
        self,
        session: Session,
        source: Source,
        politician_id: int,
        target: Region | Municipality,
        observation: TerritorialMandateObservation,
    ) -> TerritorialMandatePersistenceStatus:
        identity_key = self.mandate_identity_key(observation)
        mandate = session.scalar(
            select(TerritorialOfficeMandate).where(
                TerritorialOfficeMandate.source_id == source.id,
                TerritorialOfficeMandate.identity_key == identity_key,
            )
        )
        region_id = target.id if isinstance(target, Region) else None
        municipality_id = target.id if isinstance(target, Municipality) else None
        if mandate is None:
            session.add(
                TerritorialOfficeMandate(
                    politician_id=politician_id,
                    office=observation.office,
                    region_id=region_id,
                    municipality_id=municipality_id,
                    source_id=source.id,
                    raw_document_id=observation.raw_document_id,
                    identity_key=identity_key,
                    source_identifier=observation.source_identifier,
                    source_url=str(observation.source_url),
                    start_date=observation.start_date,
                    end_date=observation.end_date,
                )
            )
            return TerritorialMandatePersistenceStatus.CREATED
        if (
            mandate.politician_id != politician_id
            or mandate.office != observation.office
            or mandate.region_id != region_id
            or mandate.municipality_id != municipality_id
            or mandate.start_date != observation.start_date
        ):
            raise TerritoryConflictError(
                "mandate identity key resolves to conflicting source data"
            )
        changed = (
            observation.end_date is not None
            and mandate.end_date != observation.end_date
        )
        if observation.end_date is not None:
            mandate.end_date = observation.end_date
        mandate.raw_document_id = observation.raw_document_id
        mandate.source_url = str(observation.source_url)
        if observation.source_identifier is not None:
            mandate.source_identifier = observation.source_identifier
        return (
            TerritorialMandatePersistenceStatus.UPDATED
            if changed
            else TerritorialMandatePersistenceStatus.ALREADY_EXISTS
        )

    @staticmethod
    def mandate_identity_key(
        observation: TerritorialMandateObservation,
    ) -> str:
        person_key = (
            ["source_identifier", observation.politician_source_identifier]
            if observation.politician_source_identifier is not None
            else [
                "name_birth",
                normalize_person_name(
                    observation.given_name, observation.family_name
                ),
                observation.birth_date.isoformat()
                if observation.birth_date is not None
                else None,
            ]
        )
        canonical = json.dumps(
            [
                observation.source_identifier,
                person_key,
                observation.office.value,
                observation.region_istat_code,
                observation.municipality_istat_code,
                observation.start_date.isoformat(),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _detail(
        observation: TerritorialMandateObservation,
        status: TerritorialMandatePersistenceStatus,
        politician_id: int | None = None,
    ) -> TerritorialMandatePersistenceDetail:
        return TerritorialMandatePersistenceDetail(
            status=status,
            politician_id=politician_id,
            office=observation.office,
            territory_istat_code=(
                observation.municipality_istat_code
                or observation.region_istat_code
                or ""
            ),
            start_date=observation.start_date,
            end_date=observation.end_date,
        )
