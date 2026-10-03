from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import (
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    RawDocumentStatus,
    Source,
)
from backend.app.pipeline.mappers import (
    CameraCandidateProfileMapper,
    CandidateMappingError,
    CandidateProfileMapper,
    SenatoCandidateProfileMapper,
)
from backend.app.schemas import (
    BootstrapInvalidDetail,
    BootstrapMatchedDetail,
    BootstrapNewDetail,
    BootstrapReport,
    BootstrapSourceIdentifier,
    BootstrapUncertainDetail,
    CandidateProfile,
    MatchedResult,
    NewResult,
    SourceDocumentProvenance,
    UncertainResult,
)
from backend.app.services.matching_service import MatchingService, normalize_person_name


class CandidateRebuildError(RuntimeError):
    """A stored RawDocument cannot be used to rebuild candidates."""


class BootstrapError(RuntimeError):
    """Base error for controlled bootstrap failures."""


class BootstrapBlockedError(BootstrapError):
    def __init__(self, report: BootstrapReport) -> None:
        super().__init__("bootstrap is blocked by uncertain or invalid candidates")
        self.report = report


class BootstrapConflictError(BootstrapError):
    """The database changed after planning or rejected a unique identifier."""


class BootstrapApplyError(BootstrapError):
    """Creation failed and the bootstrap transaction was rolled back."""


@dataclass(frozen=True)
class IndexedCandidate:
    candidate_index: int
    profile: CandidateProfile


@dataclass(frozen=True)
class CandidateRebuildResult:
    raw_document_id: int
    candidates: tuple[IndexedCandidate, ...]
    invalid: tuple[BootstrapInvalidDetail, ...]


@dataclass(frozen=True)
class BootstrapPlan:
    report: BootstrapReport
    new_candidates: tuple[IndexedCandidate, ...]


class RawDocumentCandidateRebuilder:
    """Explicitly remap stored normalized records without changing ingestion rules."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        mappers: Mapping[str, CandidateProfileMapper] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.mappers = dict(
            mappers
            or {
                "senato-repubblica": SenatoCandidateProfileMapper(),
                "camera-deputati": CameraCandidateProfileMapper(),
            }
        )

    def rebuild(
        self,
        *,
        raw_document_id: int | None = None,
        source_key: str = "senato-repubblica",
    ) -> CandidateRebuildResult:
        with self.session_factory() as session:
            document = self._select_document(
                session,
                raw_document_id=raw_document_id,
                source_key=source_key,
            )
            self._validate_document(document, source_key)
            records = document.structured_records
            assert records is not None

            mapper = self.mappers.get(document.source.key)
            if mapper is None:
                raise CandidateRebuildError(
                    f"no candidate mapper is registered for source {document.source.key!r}"
                )
            provenance = SourceDocumentProvenance(
                source_key=document.source.key,
                raw_document_id=document.id,
                source_url=document.source_url,
                retrieved_at=document.retrieved_at,
                raw_sha256=document.raw_sha256,
                normalized_sha256=document.normalized_sha256,
                collector_version=document.collector_version,
                parser_version=document.parser_version,
            )

            candidates: list[IndexedCandidate] = []
            invalid: list[BootstrapInvalidDetail] = []
            for index, record in enumerate(records):
                if not isinstance(record, Mapping):
                    invalid.append(
                        BootstrapInvalidDetail(
                            candidate_index=index,
                            error="stored structured record is not an object",
                        )
                    )
                    continue
                try:
                    profile = mapper.map_records((record,), document=provenance)[0]
                except (CandidateMappingError, ValueError) as exc:
                    invalid.append(
                        BootstrapInvalidDetail(
                            candidate_index=index,
                            source_record_id=self._record_identifier(record),
                            display_name=self._record_display_name(record),
                            error=str(exc),
                        )
                    )
                    continue
                candidates.append(IndexedCandidate(index, profile))

            return CandidateRebuildResult(
                raw_document_id=document.id,
                candidates=tuple(candidates),
                invalid=tuple(invalid),
            )

    @staticmethod
    def _select_document(
        session: Session,
        *,
        raw_document_id: int | None,
        source_key: str,
    ) -> RawDocument:
        if raw_document_id is not None:
            document = session.get(RawDocument, raw_document_id)
            if document is None:
                raise CandidateRebuildError(
                    f"RawDocument {raw_document_id} does not exist"
                )
            return document

        document = session.scalar(
            select(RawDocument)
            .join(Source)
            .where(
                Source.key == source_key,
                RawDocument.process_status == RawDocumentStatus.PARSED,
            )
            .order_by(RawDocument.retrieved_at.desc(), RawDocument.id.desc())
            .limit(1)
        )
        if document is None:
            raise CandidateRebuildError(
                f"no successfully parsed RawDocument exists for source {source_key!r}"
            )
        return document

    @staticmethod
    def _validate_document(document: RawDocument, source_key: str) -> None:
        if document.source.key != source_key:
            raise CandidateRebuildError(
                f"RawDocument {document.id} belongs to source "
                f"{document.source.key!r}, not {source_key!r}"
            )
        if document.process_status != RawDocumentStatus.PARSED:
            raise CandidateRebuildError(
                f"RawDocument {document.id} is not successfully parsed"
            )
        if document.structured_records is None:
            raise CandidateRebuildError(
                f"RawDocument {document.id} has no structured records"
            )
        if not document.normalized_sha256:
            raise CandidateRebuildError(
                f"RawDocument {document.id} has no normalized hash"
            )

    @staticmethod
    def _record_identifier(record: Mapping[str, Any]) -> str | None:
        for field in ("senator_uri", "deputy_uri", "person_uri", "mandate_uri"):
            value = record.get(field)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _record_display_name(record: Mapping[str, Any]) -> str | None:
        names = [record.get("first_name"), record.get("last_name")]
        display_name = " ".join(
            value.strip() for value in names if isinstance(value, str) and value.strip()
        )
        return display_name or None


class PoliticianBootstrapService:
    """Plan read-only matching, then atomically create only new identities."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def plan(
        self,
        rebuilt: CandidateRebuildResult,
        *,
        dry_run: bool,
    ) -> BootstrapPlan:
        invalid = list(rebuilt.invalid)
        invalid_indices = {detail.candidate_index for detail in invalid}
        duplicate_indices, duplicate_errors = self._duplicate_identifier_errors(
            rebuilt.candidates
        )
        invalid_indices.update(duplicate_indices)
        invalid.extend(duplicate_errors)

        new_details: list[BootstrapNewDetail] = []
        matched_details: list[BootstrapMatchedDetail] = []
        uncertain_details: list[BootstrapUncertainDetail] = []
        new_candidates: list[IndexedCandidate] = []

        with self.session_factory() as session:
            known_authorities = set(session.scalars(select(Source.key)))
            matcher = MatchingService(session)
            for indexed in rebuilt.candidates:
                if indexed.candidate_index in invalid_indices:
                    continue
                validation_error = self._validate_candidate(
                    indexed.profile,
                    known_authorities,
                )
                if validation_error is not None:
                    invalid.append(
                        BootstrapInvalidDetail(
                            candidate_index=indexed.candidate_index,
                            source_record_id=self._candidate_record_id(indexed.profile),
                            display_name=self._display_name(indexed.profile),
                            error=validation_error,
                        )
                    )
                    continue

                result = matcher.match(indexed.profile)
                if isinstance(result, MatchedResult):
                    matched_details.append(
                        BootstrapMatchedDetail(
                            candidate_index=indexed.candidate_index,
                            display_name=self._display_name(indexed.profile),
                            politician_id=result.politician_id,
                            method=result.method,
                        )
                    )
                elif isinstance(result, UncertainResult):
                    uncertain_details.append(
                        BootstrapUncertainDetail(
                            candidate_index=indexed.candidate_index,
                            display_name=self._display_name(indexed.profile),
                            candidate_politician_ids=result.candidate_politician_ids,
                            method=result.method,
                        )
                    )
                elif isinstance(result, NewResult):
                    new_candidates.append(indexed)
                    new_details.append(self._new_detail(indexed))

        invalid.sort(key=lambda item: item.candidate_index)
        identifier_count = sum(
            len(candidate.profile.identity.source_identifiers)
            for candidate in new_candidates
        )
        safe_to_apply = not uncertain_details and not invalid
        report = BootstrapReport(
            raw_document_id=rebuilt.raw_document_id,
            dry_run=dry_run,
            applied=False,
            safe_to_apply=safe_to_apply,
            total_candidates=len(rebuilt.candidates) + len(rebuilt.invalid),
            new_count=len(new_details),
            matched_count=len(matched_details),
            uncertain_count=len(uncertain_details),
            invalid_count=len(invalid),
            politicians_would_create=len(new_details),
            identifiers_would_create=identifier_count,
            politicians_created=0,
            identifiers_created=0,
            new=tuple(new_details),
            matched=tuple(matched_details),
            uncertain=tuple(uncertain_details),
            invalid=tuple(invalid),
        )
        return BootstrapPlan(report=report, new_candidates=tuple(new_candidates))

    def apply(self, plan: BootstrapPlan) -> BootstrapReport:
        if not plan.report.safe_to_apply:
            raise BootstrapBlockedError(plan.report)

        created_ids: dict[int, int] = {}
        identifier_count = 0
        try:
            with self.session_factory() as session:
                with session.begin():
                    authorities = {
                        identifier.authority
                        for item in plan.new_candidates
                        for identifier in item.profile.identity.source_identifiers
                    }
                    sources = {
                        source.key: source
                        for source in session.scalars(
                            select(Source).where(Source.key.in_(authorities))
                        )
                    }
                    missing = sorted(authorities - sources.keys())
                    if missing:
                        raise BootstrapConflictError(
                            "source authorities disappeared after planning: "
                            + ", ".join(missing)
                        )

                    planned_identifiers = [
                        (identifier.authority, identifier.value)
                        for item in plan.new_candidates
                        for identifier in item.profile.identity.source_identifiers
                    ]
                    conflict_conditions = [
                        and_(
                            Source.key == authority,
                            PoliticianSourceIdentifier.value == value,
                        )
                        for authority, value in planned_identifiers
                    ]
                    conflicts = []
                    if conflict_conditions:
                        conflicts = list(
                            session.execute(
                                select(Source.key, PoliticianSourceIdentifier.value)
                                .join(
                                    PoliticianSourceIdentifier,
                                    PoliticianSourceIdentifier.source_id == Source.id,
                                )
                                .where(or_(*conflict_conditions))
                            )
                        )
                    if conflicts:
                        labels = ", ".join(
                            f"{authority}:{value}" for authority, value in conflicts
                        )
                        raise BootstrapConflictError(
                            "source identifiers were claimed after planning: " + labels
                        )

                    for item in plan.new_candidates:
                        identity = item.profile.identity
                        politician = Politician(
                            canonical_given_name=identity.given_name.strip(),
                            canonical_family_name=identity.family_name.strip(),
                            normalized_name=normalize_person_name(
                                identity.given_name,
                                identity.family_name,
                            ),
                            birth_date=identity.birth_date,
                        )
                        session.add(politician)
                        session.flush()
                        created_ids[item.candidate_index] = politician.id
                        for identifier in identity.source_identifiers:
                            session.add(
                                PoliticianSourceIdentifier(
                                    politician_id=politician.id,
                                    source_id=sources[identifier.authority].id,
                                    value=identifier.value,
                                )
                            )
                            identifier_count += 1
                    session.flush()
        except BootstrapConflictError:
            raise
        except IntegrityError as exc:
            raise BootstrapConflictError(
                "bootstrap conflicted with an existing source identifier; "
                "no politicians were created"
            ) from exc
        except Exception as exc:
            raise BootstrapApplyError(
                f"bootstrap creation failed; transaction rolled back: {exc}"
            ) from exc

        created_details = tuple(
            detail.model_copy(
                update={
                    "created_politician_id": created_ids[detail.candidate_index]
                }
            )
            for detail in plan.report.new
        )
        return plan.report.model_copy(
            update={
                "dry_run": False,
                "applied": True,
                "politicians_created": len(created_ids),
                "identifiers_created": identifier_count,
                "new": created_details,
            }
        )

    @staticmethod
    def _validate_candidate(
        candidate: CandidateProfile,
        known_authorities: set[str],
    ) -> str | None:
        identity = candidate.identity
        if not identity.given_name.strip() or not identity.family_name.strip():
            return "canonical given and family names must be non-empty"
        if not normalize_person_name(identity.given_name, identity.family_name):
            return "canonical name has no normalizable characters"
        if not identity.source_identifiers:
            return "at least one official source identifier is required"
        for identifier in identity.source_identifiers:
            if not identifier.authority.strip() or not identifier.value.strip():
                return "source identifier authority and value must be non-empty"
            if identifier.authority not in known_authorities:
                return f"unknown source authority {identifier.authority!r}"
        return None

    @staticmethod
    def _duplicate_identifier_errors(
        candidates: Sequence[IndexedCandidate],
    ) -> tuple[set[int], list[BootstrapInvalidDetail]]:
        keys_by_candidate: dict[int, list[tuple[str, str]]] = {}
        occurrences: Counter[tuple[str, str]] = Counter()
        for item in candidates:
            keys = [
                (identifier.authority, identifier.value)
                for identifier in item.profile.identity.source_identifiers
            ]
            keys_by_candidate[item.candidate_index] = keys
            occurrences.update(keys)

        invalid_indices: set[int] = set()
        errors: list[BootstrapInvalidDetail] = []
        for item in candidates:
            duplicates = sorted(
                set(
                    key
                    for key in keys_by_candidate[item.candidate_index]
                    if occurrences[key] > 1
                )
            )
            if not duplicates:
                continue
            invalid_indices.add(item.candidate_index)
            labels = ", ".join(f"{authority}:{value}" for authority, value in duplicates)
            errors.append(
                BootstrapInvalidDetail(
                    candidate_index=item.candidate_index,
                    source_record_id=PoliticianBootstrapService._candidate_record_id(
                        item.profile
                    ),
                    display_name=PoliticianBootstrapService._display_name(item.profile),
                    error=f"duplicate source identifier in bootstrap batch: {labels}",
                )
            )
        return invalid_indices, errors

    @staticmethod
    def _display_name(candidate: CandidateProfile) -> str:
        return f"{candidate.identity.given_name} {candidate.identity.family_name}".strip()

    @staticmethod
    def _candidate_record_id(candidate: CandidateProfile) -> str | None:
        identifiers = candidate.identity.source_identifiers
        return identifiers[0].value if identifiers else None

    @staticmethod
    def _new_detail(item: IndexedCandidate) -> BootstrapNewDetail:
        identity = item.profile.identity
        return BootstrapNewDetail(
            candidate_index=item.candidate_index,
            display_name=PoliticianBootstrapService._display_name(item.profile),
            birth_date=identity.birth_date,
            source_identifiers=tuple(
                BootstrapSourceIdentifier(
                    authority=identifier.authority,
                    value=identifier.value,
                )
                for identifier in identity.source_identifiers
            ),
        )
