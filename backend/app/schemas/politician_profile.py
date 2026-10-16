from datetime import date, datetime

from pydantic import AnyHttpUrl, Field, field_validator

from backend.app.models.politician_profile import (
    DatePrecision,
    ProceedingOutcome,
    ProceedingType,
    ProfileContentKind,
    ProfileContentStatus,
    ProfileSourceKind,
)
from backend.app.schemas.candidate_profile import ImmutableSchema


class ProfileSourceInput(ImmutableSchema):
    title: str | None = Field(default=None, max_length=500)
    name: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl | None = None
    kind: ProfileSourceKind
    excerpt: str | None = Field(default=None, max_length=4000)

    @field_validator("title", "name", "excerpt")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class BiographyDraftInput(ImmutableSchema):
    identity_key: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=20000)
    sources: tuple[ProfileSourceInput, ...] = ()
    created_by: str = Field(min_length=1, max_length=200)

    @field_validator("body", "identity_key", "created_by")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CareerEntryDraftInput(ImmutableSchema):
    identity_key: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date | None = None
    start_precision: DatePrecision = DatePrecision.YEAR
    end_precision: DatePrecision | None = None
    is_current: bool = False
    role: str = Field(min_length=1, max_length=500)
    institution: str = Field(min_length=1, max_length=500)
    organization: str | None = Field(default=None, max_length=500)
    party_or_group: str | None = Field(default=None, max_length=500)
    sources: tuple[ProfileSourceInput, ...] = ()
    created_by: str = Field(min_length=1, max_length=200)


class PositionDraftInput(ImmutableSchema):
    identity_key: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=200)
    position_statement: str = Field(min_length=1, max_length=4000)
    verifiable_statement: str = Field(min_length=1, max_length=4000)
    statement_date: date | None = None
    statement_precision: DatePrecision | None = None
    sources: tuple[ProfileSourceInput, ...] = ()
    created_by: str = Field(min_length=1, max_length=200)


class ProceedingDraftInput(ImmutableSchema):
    identity_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    proceeding_types: tuple[ProceedingType, ...] = Field(min_length=1)
    event_date: date | None = None
    event_precision: DatePrecision | None = None
    outcome: ProceedingOutcome | None = None
    outcome_date: date | None = None
    summary: str = Field(min_length=1, max_length=8000)
    outcome_summary: str | None = Field(default=None, max_length=4000)
    sources: tuple[ProfileSourceInput, ...] = ()
    created_by: str = Field(min_length=1, max_length=200)


class PublicProfileSource(ImmutableSchema):
    title: str | None = None
    name: str
    url: AnyHttpUrl | None = None
    kind: ProfileSourceKind
    excerpt: str | None = None


class PublicBiography(ImmutableSchema):
    body: str
    sources: tuple[PublicProfileSource, ...] = ()
    published_at: datetime


class PublicCareerEntry(ImmutableSchema):
    start_date: date
    end_date: date | None
    start_precision: DatePrecision
    end_precision: DatePrecision | None
    is_current: bool
    role: str
    institution: str
    organization: str | None = None
    party_or_group: str | None = None
    sources: tuple[PublicProfileSource, ...] = ()


class PublicPosition(ImmutableSchema):
    topic: str
    position_statement: str
    verifiable_statement: str
    statement_date: date | None
    statement_precision: DatePrecision | None
    sources: tuple[PublicProfileSource, ...] = ()


class PublicProceeding(ImmutableSchema):
    title: str
    proceeding_types: tuple[ProceedingType, ...]
    event_date: date | None
    event_precision: DatePrecision | None
    outcome: ProceedingOutcome | None
    outcome_date: date | None
    summary: str
    outcome_summary: str | None
    sources: tuple[PublicProfileSource, ...] = ()


class AdminProfileContentItem(ImmutableSchema):
    id: int
    politician_id: int
    kind: ProfileContentKind
    identity_key: str
    status: ProfileContentStatus
    title: str
    sources_incomplete: bool
    created_by: str
    reviewed_by: str | None
    published_at: datetime | None
    created_at: datetime


class AdminProfileContentList(ImmutableSchema):
    items: tuple[AdminProfileContentItem, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class AdminProfileContentDetail(ImmutableSchema):
    id: int
    politician_id: int
    kind: ProfileContentKind
    identity_key: str
    status: ProfileContentStatus
    created_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    published_at: datetime | None
    review_note: str | None
    sources: tuple[PublicProfileSource, ...]
    sources_incomplete: bool
    body: str | None = None
    topic: str | None = None
    title: str | None = None
    summary: str | None = None
    role: str | None = None
    institution: str | None = None
    proceeding_types: tuple[ProceedingType, ...] | None = None
    outcome: ProceedingOutcome | None = None
