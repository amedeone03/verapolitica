from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.models import Politician, PoliticianSourceIdentifier, Source
from backend.app.schemas import (
    CandidateProfile,
    MatchedResult,
    MatchingMethod,
    MatchingResult,
)
from backend.app.services.matching_service import MatchingService


class IdentityServiceError(RuntimeError):
    """Base error for controlled official-identity persistence failures."""


class IdentityValidationError(IdentityServiceError):
    """The candidate or supplied deterministic match is not safe to link."""


class IdentityConflictError(IdentityServiceError):
    """An official identifier belongs to another Politician."""


class IdentityPersistenceError(IdentityServiceError):
    """Identifier persistence failed and the transaction was rolled back."""


class IdentifierAttachmentStatus(StrEnum):
    ATTACHED = "attached"
    ALREADY_EXISTS = "already_exists"


@dataclass(frozen=True, slots=True)
class IdentifierAttachmentResult:
    politician_id: int
    source_authority: str
    source_identifier: str
    status: IdentifierAttachmentStatus


@dataclass(frozen=True, slots=True)
class IdentityResolutionResult:
    match: MatchingResult
    attachments: tuple[IdentifierAttachmentResult, ...] = ()


class PoliticianIdentityService:
    """Transactionally attach official identifiers after a safe match."""

    allowed_methods = {
        MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
        MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
    }

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def attach_candidate_identifiers(
        self,
        candidate: CandidateProfile,
        match: MatchedResult,
    ) -> tuple[IdentifierAttachmentResult, ...]:
        if match.method not in self.allowed_methods:
            raise IdentityValidationError(
                f"matching method {match.method!r} is not safe for identity linking"
            )
        try:
            with self.session_factory() as session:
                with session.begin():
                    results = self._attach_in_session(
                        session,
                        candidate,
                        politician_id=match.politician_id,
                        deterministic_match=match,
                    )
            return tuple(results)
        except (IdentityValidationError, IdentityConflictError):
            raise
        except IntegrityError as exc:
            raise IdentityConflictError(
                "official identifier attachment conflicted with another write; "
                "transaction rolled back"
            ) from exc
        except Exception as exc:
            raise IdentityPersistenceError(
                f"identity attachment failed; transaction rolled back: {exc}"
            ) from exc

    def attach_candidate_identifiers_for_manual_resolution(
        self,
        session: Session,
        candidate: CandidateProfile,
        *,
        politician_id: int,
    ) -> tuple[IdentifierAttachmentResult, ...]:
        """Attach identifiers inside the caller's explicit editorial transaction.

        This deliberately skips automatic-match verification because a human case
        decision supplies the authorization. Source and ownership validation remain
        identical to the automatic path.
        """

        return self._attach_in_session(
            session,
            candidate,
            politician_id=politician_id,
            deterministic_match=None,
        )

    def _attach_in_session(
        self,
        session: Session,
        candidate: CandidateProfile,
        *,
        politician_id: int,
        deterministic_match: MatchedResult | None,
    ) -> tuple[IdentifierAttachmentResult, ...]:
        identifiers = self._validated_identifiers(candidate)
        politician = session.scalar(
            select(Politician)
            .where(Politician.id == politician_id)
            .with_for_update()
        )
        if politician is None:
            raise IdentityValidationError(
                f"Politician {politician_id} does not exist"
            )

        sources = {
            source.key: source
            for source in session.scalars(
                select(Source).where(
                    Source.key.in_({authority for authority, _ in identifiers})
                )
            )
        }
        missing = sorted({authority for authority, _ in identifiers} - sources.keys())
        if missing:
            raise IdentityValidationError(
                "unknown source authorities: " + ", ".join(missing)
            )

        existing = {
            (source_key, value): owner_id
            for source_key, value, owner_id in session.execute(
                select(
                    Source.key,
                    PoliticianSourceIdentifier.value,
                    PoliticianSourceIdentifier.politician_id,
                )
                .join(
                    PoliticianSourceIdentifier,
                    PoliticianSourceIdentifier.source_id == Source.id,
                )
                .where(
                    Source.key.in_({authority for authority, _ in identifiers}),
                    PoliticianSourceIdentifier.value.in_(
                        {value for _, value in identifiers}
                    ),
                )
            )
            if (source_key, value) in identifiers
        }
        conflicts = [
            (authority, value, existing[(authority, value)])
            for authority, value in identifiers
            if (authority, value) in existing
            and existing[(authority, value)] != politician.id
        ]
        if conflicts:
            authority, value, owner_id = conflicts[0]
            raise IdentityConflictError(
                f"identifier {authority}:{value} already belongs to "
                f"Politician {owner_id}"
            )

        if deterministic_match is not None:
            verified = MatchingService(session).match(candidate)
            if not isinstance(verified, MatchedResult):
                raise IdentityValidationError(
                    "candidate no longer has one deterministic match"
                )
            if verified.politician_id != politician.id:
                raise IdentityConflictError(
                    "candidate now resolves to a different Politician"
                )
            if verified.method not in self.allowed_methods:
                raise IdentityValidationError(
                    f"verified matching method {verified.method!r} is unsafe"
                )

        results: list[IdentifierAttachmentResult] = []
        for authority, value in identifiers:
            if (authority, value) in existing:
                status = IdentifierAttachmentStatus.ALREADY_EXISTS
            else:
                session.add(
                    PoliticianSourceIdentifier(
                        politician_id=politician.id,
                        source_id=sources[authority].id,
                        value=value,
                    )
                )
                status = IdentifierAttachmentStatus.ATTACHED
            results.append(
                IdentifierAttachmentResult(
                    politician_id=politician.id,
                    source_authority=authority,
                    source_identifier=value,
                    status=status,
                )
            )
        session.flush()
        return tuple(results)

    @staticmethod
    def _validated_identifiers(
        candidate: CandidateProfile,
    ) -> tuple[tuple[str, str], ...]:
        identifiers = tuple(
            dict.fromkeys(
                (identifier.authority, identifier.value)
                for identifier in candidate.identity.source_identifiers
            )
        )
        if not identifiers:
            raise IdentityValidationError(
                "candidate has no official source identifiers to attach"
            )
        for authority, value in identifiers:
            if not authority.strip() or not value.strip():
                raise IdentityValidationError(
                    "source authority and identifier value must be non-empty"
                )
            if authority != candidate.provenance.document.source_key:
                raise IdentityValidationError(
                    f"identifier authority {authority!r} is not supported by the "
                    f"candidate document source {candidate.provenance.document.source_key!r}"
                )
        return identifiers


class CandidateIdentityCoordinator:
    """Compose read-only matching with explicit safe identity persistence."""

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

    def match_and_link(self, candidate: CandidateProfile) -> IdentityResolutionResult:
        with self.session_factory() as session:
            match = MatchingService(session).match(candidate)
        if not isinstance(match, MatchedResult):
            return IdentityResolutionResult(match=match)
        attachments = self.identity_service.attach_candidate_identifiers(
            candidate, match
        )
        return IdentityResolutionResult(match=match, attachments=attachments)
