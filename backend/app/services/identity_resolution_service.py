from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload, sessionmaker

from backend.app.models import (
    IdentityResolutionCase,
    IdentityResolutionStatus,
    Politician,
    PoliticianSourceIdentifier,
    RawDocument,
    Source,
)
from backend.app.schemas import (
    CandidateProfile,
    IdentityResolutionAttachment,
    IdentityResolutionCaseResult,
    IdentityResolutionDecisionResult,
    MatchedResult,
    MatchingResult,
    NewMatchReason,
    NewResult,
    UncertainResult,
)
from backend.app.services.matching_service import MatchingService, normalize_person_name
from backend.app.services.politician_identity_service import (
    CandidateIdentityCoordinator,
    IdentifierAttachmentResult,
    IdentityConflictError,
    IdentityResolutionResult,
    IdentityValidationError,
    PoliticianIdentityService,
)


class IdentityResolutionServiceError(RuntimeError):
    """Base error for controlled human identity-resolution failures."""


class IdentityResolutionInputError(IdentityResolutionServiceError):
    """Candidate or editorial input is invalid."""


class IdentityResolutionCaseNotFoundError(IdentityResolutionServiceError):
    """The requested resolution case does not exist."""


class IdentityResolutionStateError(IdentityResolutionServiceError):
    """The case is terminal or otherwise cannot accept the requested action."""


class IdentityResolutionConflictError(IdentityResolutionServiceError):
    """Identity ownership or a concurrent resolution conflicts with the action."""


class IdentityResolutionPersistenceError(IdentityResolutionServiceError):
    """Persistence failed and the explicit transaction was rolled back."""


@dataclass(frozen=True, slots=True)
class SuggestedSourceIdentifier:
    authority: str
    value: str


@dataclass(frozen=True, slots=True)
class PossibleIdentityMatch:
    politician_id: int
    given_name: str
    family_name: str
    birth_date: date | None
    current_version_id: int | None
    signals: tuple[str, ...]
    source_identifiers: tuple[SuggestedSourceIdentifier, ...]


@dataclass(frozen=True, slots=True)
class CandidateIdentityProcessingResult:
    match: MatchingResult
    automatic_resolution: IdentityResolutionResult | None = None
    case: IdentityResolutionCaseResult | None = None


_MATCHING_RESULT_ADAPTER = TypeAdapter(MatchingResult)


def _normalize_editorial_input(
    reviewer_identity: str,
    note: str | None,
) -> tuple[str, str | None]:
    reviewer = reviewer_identity.strip()
    if not reviewer:
        raise IdentityResolutionInputError("reviewer identity must be non-empty")
    if len(reviewer) > 200:
        raise IdentityResolutionInputError(
            "reviewer identity must be at most 200 characters"
        )
    normalized_note = note.strip() if note is not None else None
    if normalized_note and len(normalized_note) > 5000:
        raise IdentityResolutionInputError(
            "resolution note must be at most 5000 characters"
        )
    return reviewer, normalized_note or None


class IdentityResolutionService:
    """Persist and transactionally resolve human identity-review cases."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        identity_service: PoliticianIdentityService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.identity_service = identity_service or PoliticianIdentityService(
            session_factory
        )

    def create_or_reuse_case(
        self,
        candidate: CandidateProfile,
        match: MatchingResult,
    ) -> IdentityResolutionCaseResult | None:
        if isinstance(match, MatchedResult):
            return None
        source_key, source_identifier = self._case_key(candidate)
        display_name = (
            candidate.identity.display_name
            or f"{candidate.identity.given_name} {candidate.identity.family_name}"
        ).strip()
        if not display_name:
            raise IdentityResolutionInputError(
                "candidate display name must be non-empty"
            )

        try:
            with self.session_factory() as session:
                with session.begin():
                    source = session.scalar(
                        select(Source).where(Source.key == source_key)
                    )
                    if source is None:
                        raise IdentityResolutionInputError(
                            f"unknown candidate source {source_key!r}"
                        )
                    document = session.get(
                        RawDocument, candidate.provenance.document.raw_document_id
                    )
                    if document is None or document.source_id != source.id:
                        raise IdentityResolutionInputError(
                            "candidate RawDocument does not belong to its source"
                        )
                    verified_match = MatchingService(session).match(candidate)
                    if not self._requires_manual_resolution(verified_match):
                        return None
                    existing = session.scalar(
                        select(IdentityResolutionCase).where(
                            IdentityResolutionCase.source_id == source.id,
                            IdentityResolutionCase.source_identifier
                            == source_identifier,
                        )
                    )
                    if existing is not None:
                        return self._case_result(existing, created=False)

                    case = IdentityResolutionCase(
                        raw_document_id=document.id,
                        source_id=source.id,
                        source_identifier=source_identifier,
                        candidate_display_name=display_name,
                        candidate_snapshot=candidate.model_dump(mode="json"),
                        matching_result_data=verified_match.model_dump(mode="json"),
                        status=IdentityResolutionStatus.PENDING,
                    )
                    session.add(case)
                    session.flush()
                    result = self._case_result(case, created=True)
            return result
        except IdentityResolutionServiceError:
            raise
        except IntegrityError:
            with self.session_factory() as session:
                existing = session.scalar(
                    select(IdentityResolutionCase)
                    .join(Source)
                    .where(
                        Source.key == source_key,
                        IdentityResolutionCase.source_identifier
                        == source_identifier,
                    )
                )
                if existing is not None:
                    return self._case_result(existing, created=False)
            raise IdentityResolutionConflictError(
                "identity-resolution case conflicted with another write"
            )
        except Exception as exc:
            raise IdentityResolutionPersistenceError(
                f"identity-resolution case creation failed; transaction rolled back: {exc}"
            ) from exc

    def resolve_to_existing(
        self,
        case_id: int,
        politician_id: int,
        *,
        reviewer_identity: str,
        note: str | None = None,
    ) -> IdentityResolutionDecisionResult:
        reviewer, normalized_note = _normalize_editorial_input(
            reviewer_identity, note
        )
        try:
            with self.session_factory() as session:
                with session.begin():
                    case = self._load_pending_case(session, case_id)
                    candidate = self._candidate(case)
                    attach_identifiers = (
                        self.identity_service
                        .attach_candidate_identifiers_for_manual_resolution
                    )
                    attachments = attach_identifiers(
                        session,
                        candidate,
                        politician_id=politician_id,
                    )
                    result = self._finish_case(
                        case,
                        status=IdentityResolutionStatus.RESOLVED_EXISTING,
                        politician_id=politician_id,
                        reviewer=reviewer,
                        note=normalized_note,
                        attachments=attachments,
                    )
                    session.flush()
            return result
        except IdentityResolutionServiceError:
            raise
        except IdentityConflictError as exc:
            raise IdentityResolutionConflictError(str(exc)) from exc
        except IdentityValidationError as exc:
            raise IdentityResolutionInputError(str(exc)) from exc
        except IntegrityError as exc:
            raise IdentityResolutionConflictError(
                "identity resolution conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise IdentityResolutionPersistenceError(
                f"resolve-existing failed; transaction rolled back: {exc}"
            ) from exc

    def resolve_as_new(
        self,
        case_id: int,
        *,
        reviewer_identity: str,
        note: str | None = None,
    ) -> IdentityResolutionDecisionResult:
        reviewer, normalized_note = _normalize_editorial_input(
            reviewer_identity, note
        )
        try:
            with self.session_factory() as session:
                with session.begin():
                    case = self._load_pending_case(session, case_id)
                    candidate = self._candidate(case)
                    identity = candidate.identity
                    given_name = identity.given_name.strip()
                    family_name = identity.family_name.strip()
                    normalized_name = normalize_person_name(given_name, family_name)
                    if not given_name or not family_name or not normalized_name:
                        raise IdentityResolutionInputError(
                            "candidate lacks a valid structured canonical name"
                        )
                    politician = Politician(
                        canonical_given_name=given_name,
                        canonical_family_name=family_name,
                        normalized_name=normalized_name,
                        birth_date=identity.birth_date,
                    )
                    session.add(politician)
                    session.flush()
                    attach_identifiers = (
                        self.identity_service
                        .attach_candidate_identifiers_for_manual_resolution
                    )
                    attachments = attach_identifiers(
                        session,
                        candidate,
                        politician_id=politician.id,
                    )
                    result = self._finish_case(
                        case,
                        status=IdentityResolutionStatus.RESOLVED_NEW,
                        politician_id=politician.id,
                        reviewer=reviewer,
                        note=normalized_note,
                        attachments=attachments,
                    )
                    session.flush()
            return result
        except IdentityResolutionServiceError:
            raise
        except IdentityConflictError as exc:
            raise IdentityResolutionConflictError(str(exc)) from exc
        except IdentityValidationError as exc:
            raise IdentityResolutionInputError(str(exc)) from exc
        except IntegrityError as exc:
            raise IdentityResolutionConflictError(
                "identity resolution conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise IdentityResolutionPersistenceError(
                f"resolve-new failed; transaction rolled back: {exc}"
            ) from exc

    def ignore(
        self,
        case_id: int,
        *,
        reviewer_identity: str,
        note: str | None = None,
    ) -> IdentityResolutionDecisionResult:
        reviewer, normalized_note = _normalize_editorial_input(
            reviewer_identity, note
        )
        try:
            with self.session_factory() as session:
                with session.begin():
                    case = self._load_pending_case(session, case_id)
                    result = self._finish_case(
                        case,
                        status=IdentityResolutionStatus.IGNORED,
                        politician_id=None,
                        reviewer=reviewer,
                        note=normalized_note,
                        attachments=(),
                    )
                    session.flush()
            return result
        except IdentityResolutionServiceError:
            raise
        except IntegrityError as exc:
            raise IdentityResolutionConflictError(
                "identity resolution conflicted with another write; transaction rolled back"
            ) from exc
        except Exception as exc:
            raise IdentityResolutionPersistenceError(
                f"ignore failed; transaction rolled back: {exc}"
            ) from exc

    def possible_matches(self, case_id: int) -> tuple[PossibleIdentityMatch, ...]:
        with self.session_factory() as session:
            case = session.get(IdentityResolutionCase, case_id)
            if case is None:
                raise IdentityResolutionCaseNotFoundError(
                    f"IdentityResolutionCase {case_id} does not exist"
                )
            candidate = self._candidate(case)
            normalized_name = normalize_person_name(
                candidate.identity.given_name,
                candidate.identity.family_name,
            )
            matching_result = self._matching_result(case)
            suggested_ids = set()
            if isinstance(matching_result, UncertainResult):
                suggested_ids.update(matching_result.candidate_politician_ids)
            identifier_keys = {
                (identifier.authority, identifier.value)
                for identifier in candidate.identity.source_identifiers
            }
            query = select(Politician).options(
                selectinload(Politician.source_identifiers).selectinload(
                    PoliticianSourceIdentifier.source
                )
            )
            conditions = [Politician.normalized_name == normalized_name]
            if suggested_ids:
                conditions.append(Politician.id.in_(suggested_ids))
            politicians = list(
                session.scalars(
                    query.where(or_(*conditions)).order_by(Politician.id)
                ).unique()
            )
            results = []
            for politician in politicians:
                signals = []
                if politician.normalized_name == normalized_name:
                    signals.append("normalized_full_name")
                if (
                    candidate.identity.birth_date is not None
                    and politician.birth_date == candidate.identity.birth_date
                ):
                    signals.append("exact_birth_date")
                if politician.id in suggested_ids:
                    signals.append("original_uncertain_result")
                if any(
                    (identifier.source.key, identifier.value) in identifier_keys
                    for identifier in politician.source_identifiers
                ):
                    signals.append("official_source_identifier")
                identifiers = tuple(
                    SuggestedSourceIdentifier(
                        authority=identifier.source.key,
                        value=identifier.value,
                    )
                    for identifier in sorted(
                        politician.source_identifiers,
                        key=lambda item: (item.source.key, item.value),
                    )
                )
                results.append(
                    PossibleIdentityMatch(
                        politician_id=politician.id,
                        given_name=politician.canonical_given_name,
                        family_name=politician.canonical_family_name,
                        birth_date=politician.birth_date,
                        current_version_id=politician.current_version_id,
                        signals=tuple(signals),
                        source_identifiers=identifiers,
                    )
                )
            return tuple(results)

    @staticmethod
    def _requires_manual_resolution(match: MatchingResult) -> bool:
        return isinstance(match, UncertainResult) or (
            isinstance(match, NewResult)
            and match.reason is NewMatchReason.INSUFFICIENT_FALLBACK_IDENTITY
        )

    @staticmethod
    def _case_key(candidate: CandidateProfile) -> tuple[str, str]:
        source_key = candidate.provenance.document.source_key
        values = sorted(
            {
                identifier.value
                for identifier in candidate.identity.source_identifiers
                if identifier.authority == source_key and identifier.value.strip()
            }
        )
        if not values:
            raise IdentityResolutionInputError(
                "candidate has no official identifier for its document source"
            )
        return source_key, values[0]

    @staticmethod
    def _case_result(
        case: IdentityResolutionCase,
        *,
        created: bool,
    ) -> IdentityResolutionCaseResult:
        return IdentityResolutionCaseResult(
            outcome="case_created" if created else "case_reused",
            case_id=case.id,
            status=case.status,
            created=created,
        )

    @staticmethod
    def _load_pending_case(
        session: Session,
        case_id: int,
    ) -> IdentityResolutionCase:
        case = session.scalar(
            select(IdentityResolutionCase)
            .where(IdentityResolutionCase.id == case_id)
            .with_for_update()
        )
        if case is None:
            raise IdentityResolutionCaseNotFoundError(
                f"IdentityResolutionCase {case_id} does not exist"
            )
        if case.status is not IdentityResolutionStatus.PENDING:
            raise IdentityResolutionStateError(
                f"identity-resolution case {case.id} cannot be resolved from "
                f"status {case.status.value!r}"
            )
        return case

    @staticmethod
    def _candidate(case: IdentityResolutionCase) -> CandidateProfile:
        try:
            return CandidateProfile.model_validate(case.candidate_snapshot)
        except ValidationError as exc:
            raise IdentityResolutionInputError(
                f"identity-resolution case {case.id} has an invalid candidate snapshot"
            ) from exc

    @staticmethod
    def _matching_result(case: IdentityResolutionCase) -> MatchingResult:
        try:
            return _MATCHING_RESULT_ADAPTER.validate_python(case.matching_result_data)
        except ValidationError as exc:
            raise IdentityResolutionInputError(
                f"identity-resolution case {case.id} has invalid matching metadata"
            ) from exc

    @staticmethod
    def _finish_case(
        case: IdentityResolutionCase,
        *,
        status: IdentityResolutionStatus,
        politician_id: int | None,
        reviewer: str,
        note: str | None,
        attachments: tuple[IdentifierAttachmentResult, ...],
    ) -> IdentityResolutionDecisionResult:
        resolved_at = datetime.now(timezone.utc)
        case.status = status
        case.resolved_politician_id = politician_id
        case.reviewer_identity = reviewer
        case.resolution_note = note
        case.resolved_at = resolved_at
        return IdentityResolutionDecisionResult(
            case_id=case.id,
            status=status,
            resolved_politician_id=politician_id,
            reviewer_identity=reviewer,
            resolution_note=note,
            resolved_at=resolved_at,
            attachments=tuple(
                IdentityResolutionAttachment(
                    source_authority=item.source_authority,
                    source_identifier=item.source_identifier,
                    status=item.status.value,
                )
                for item in attachments
            ),
        )


class HumanIdentityResolutionCoordinator:
    """Route deterministic matches or persist an explicit manual-review case."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        automatic_coordinator: CandidateIdentityCoordinator | None = None,
        resolution_service: IdentityResolutionService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.automatic_coordinator = automatic_coordinator or (
            CandidateIdentityCoordinator(session_factory)
        )
        self.resolution_service = resolution_service or IdentityResolutionService(
            session_factory
        )

    def process(self, candidate: CandidateProfile) -> CandidateIdentityProcessingResult:
        with self.session_factory() as session:
            match = MatchingService(session).match(candidate)
        if isinstance(match, MatchedResult):
            automatic = self.automatic_coordinator.match_and_link(candidate)
            if not isinstance(automatic.match, MatchedResult):
                case = self.resolution_service.create_or_reuse_case(
                    candidate, automatic.match
                )
                return CandidateIdentityProcessingResult(
                    match=automatic.match,
                    automatic_resolution=automatic,
                    case=case,
                )
            return CandidateIdentityProcessingResult(
                match=automatic.match,
                automatic_resolution=automatic,
            )
        case = self.resolution_service.create_or_reuse_case(candidate, match)
        return CandidateIdentityProcessingResult(match=match, case=case)
