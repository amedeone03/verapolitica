from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import AnyHttpUrl, Field, field_validator

from backend.app.schemas.candidate_profile import (
    BirthPlace,
    Gender,
    ImmutableSchema,
    PoliticalMandate,
)


class PoliticianVersionProfile(ImmutableSchema):
    given_name: str
    family_name: str
    birth_date: date | None = None
    birth_place: BirthPlace | None = None
    gender: Gender | None = None
    profession: str | None = None
    image_url: AnyHttpUrl | None = None
    official_homepage_url: AnyHttpUrl | None = None
    mandates: tuple[PoliticalMandate, ...]


class MatchingStatus(StrEnum):
    MATCHED = "matched"
    NEW = "new"
    UNCERTAIN = "uncertain"


class MatchingMethod(StrEnum):
    OFFICIAL_SOURCE_IDENTIFIER = "official_source_identifier"
    NORMALIZED_NAME_BIRTH_DATE = "normalized_name_birth_date"


class NewMatchReason(StrEnum):
    NO_MATCH = "no_match"
    INSUFFICIENT_FALLBACK_IDENTITY = "insufficient_fallback_identity"


class MatchedResult(ImmutableSchema):
    status: Literal[MatchingStatus.MATCHED] = MatchingStatus.MATCHED
    politician_id: int = Field(gt=0)
    method: MatchingMethod


class NewResult(ImmutableSchema):
    status: Literal[MatchingStatus.NEW] = MatchingStatus.NEW
    reason: NewMatchReason


class UncertainResult(ImmutableSchema):
    status: Literal[MatchingStatus.UNCERTAIN] = MatchingStatus.UNCERTAIN
    candidate_politician_ids: tuple[int, ...] = Field(min_length=2)
    method: MatchingMethod

    @field_validator("candidate_politician_ids")
    @classmethod
    def require_unique_sorted_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        unique_ids = tuple(sorted(set(value)))
        if len(unique_ids) < 2:
            raise ValueError("uncertain matching requires at least two politicians")
        if any(identifier <= 0 for identifier in unique_ids):
            raise ValueError("candidate politician IDs must be positive")
        return unique_ids


MatchingResult: TypeAlias = Annotated[
    MatchedResult | NewResult | UncertainResult,
    Field(discriminator="status"),
]
