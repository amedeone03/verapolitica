import re
import unicodedata

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.models import Politician, PoliticianSourceIdentifier, Source
from backend.app.schemas import (
    CandidateProfile,
    MatchedResult,
    MatchingMethod,
    MatchingResult,
    NewMatchReason,
    NewResult,
    UncertainResult,
)


def normalize_person_name(given_name: str, family_name: str) -> str:
    """Produce a deterministic, non-fuzzy name key for identity matching."""

    combined = unicodedata.normalize("NFKD", f"{given_name} {family_name}")
    without_marks = "".join(
        character
        for character in combined
        if not unicodedata.combining(character)
    ).casefold()
    alphanumeric = "".join(
        character if character.isalnum() else " " for character in without_marks
    )
    return re.sub(r"\s+", " ", alphanumeric).strip()


class MatchingService:
    """Read-only deterministic CandidateProfile identity matching."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def match(self, candidate: CandidateProfile) -> MatchingResult:
        with self.session.no_autoflush:
            identifier_matches = self._match_source_identifiers(candidate)
            if len(identifier_matches) == 1:
                return MatchedResult(
                    politician_id=identifier_matches[0],
                    method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
                )
            if len(identifier_matches) > 1:
                return UncertainResult(
                    candidate_politician_ids=identifier_matches,
                    method=MatchingMethod.OFFICIAL_SOURCE_IDENTIFIER,
                )

            birth_date = candidate.identity.birth_date
            if birth_date is None:
                return NewResult(
                    reason=NewMatchReason.INSUFFICIENT_FALLBACK_IDENTITY
                )

            normalized_name = normalize_person_name(
                candidate.identity.given_name,
                candidate.identity.family_name,
            )
            fallback_matches = tuple(
                sorted(
                    set(
                        self.session.scalars(
                            select(Politician.id).where(
                                Politician.normalized_name == normalized_name,
                                Politician.birth_date == birth_date,
                            )
                        )
                    )
                )
            )
            if len(fallback_matches) == 1:
                return MatchedResult(
                    politician_id=fallback_matches[0],
                    method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
                )
            if len(fallback_matches) > 1:
                return UncertainResult(
                    candidate_politician_ids=fallback_matches,
                    method=MatchingMethod.NORMALIZED_NAME_BIRTH_DATE,
                )
            return NewResult(reason=NewMatchReason.NO_MATCH)

    def _match_source_identifiers(
        self, candidate: CandidateProfile
    ) -> tuple[int, ...]:
        conditions = [
            and_(
                Source.key == identifier.authority,
                PoliticianSourceIdentifier.value == identifier.value,
            )
            for identifier in candidate.identity.source_identifiers
        ]
        if not conditions:
            return ()

        matches = self.session.scalars(
            select(PoliticianSourceIdentifier.politician_id)
            .join(Source, Source.id == PoliticianSourceIdentifier.source_id)
            .where(or_(*conditions))
        )
        return tuple(sorted(set(matches)))
