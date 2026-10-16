from datetime import date, datetime
from enum import StrEnum

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


class SourceCompleteness(StrEnum):
    READY_FOR_EDITORIAL_REVIEW = "READY_FOR_EDITORIAL_REVIEW"
    MISSING_SOURCE_URL = "MISSING_SOURCE_URL"
    MISSING_SOURCE_METADATA = "MISSING_SOURCE_METADATA"
    NEEDS_FACT_CHECK = "NEEDS_FACT_CHECK"
    OTHER_BLOCKER = "OTHER_BLOCKER"


class PledgeEvidenceReadiness(StrEnum):
    PLEDGE_READY_FOR_REVIEW = "PLEDGE_READY_FOR_REVIEW"
    PLEDGE_NEEDS_CLASSIFICATION = "PLEDGE_NEEDS_CLASSIFICATION"
    ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE = "ASSESSMENT_NEEDS_OFFICIAL_EVIDENCE"
    ASSESSMENT_EVIDENCE_AVAILABLE = "ASSESSMENT_EVIDENCE_AVAILABLE"


class ProceedingNature(StrEnum):
    PERSONAL_JUDICIAL_PROCEEDING = "personal_judicial_proceeding"
    POLITICAL_LEGAL_MEDIA_CONTROVERSY = "political_legal_media_controversy"
    MIXED_JUDICIAL_AND_CONTROVERSY = "mixed_judicial_and_controversy"


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
    politician_name: str
    kind: ProfileContentKind
    identity_key: str
    status: ProfileContentStatus
    title: str
    proposed_text: str
    sources: tuple[PublicProfileSource, ...] = ()
    source_names: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    source_kinds: tuple[ProfileSourceKind, ...] = ()
    sources_incomplete: bool
    source_completeness: SourceCompleteness
    completeness_blockers: tuple[str, ...] = ()
    incomplete_secondary_sources: tuple[str, ...] = ()
    created_by: str
    reference_origin: bool
    ceo_reference_warning: str | None = None
    reviewed_by: str | None
    published_at: datetime | None
    created_at: datetime
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    role: str | None = None
    institution: str | None = None
    organization: str | None = None
    party_or_group: str | None = None
    topic: str | None = None
    position_statement: str | None = None
    verifiable_statement: str | None = None
    statement_date: date | None = None
    proceeding_types: tuple[ProceedingType, ...] | None = None
    proceeding_nature: ProceedingNature | None = None
    outcome: ProceedingOutcome | None = None
    outcome_summary: str | None = None
    event_date: date | None = None


class AdminProfileContentList(ImmutableSchema):
    items: tuple[AdminProfileContentItem, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class AdminProfileContentDetail(AdminProfileContentItem):
    reviewed_at: datetime | None = None
    review_note: str | None = None
    body: str | None = None
    summary: str | None = None


class EditorialPreviewBanner(ImmutableSchema):
    editorial_preview: bool = True
    banner: str
    publication_unchanged: bool = True


class EditorialPreviewBiography(ImmutableSchema):
    body: str
    sources: tuple[PublicProfileSource, ...] = ()
    status: ProfileContentStatus
    identity_key: str
    source_completeness: SourceCompleteness
    ceo_reference_warning: str | None = None


class EditorialPreviewCareerEntry(PublicCareerEntry):
    status: ProfileContentStatus
    identity_key: str
    source_completeness: SourceCompleteness
    ceo_reference_warning: str | None = None


class EditorialPreviewPosition(PublicPosition):
    status: ProfileContentStatus
    identity_key: str
    source_completeness: SourceCompleteness
    ceo_reference_warning: str | None = None


class EditorialPreviewProceeding(PublicProceeding):
    status: ProfileContentStatus
    identity_key: str
    source_completeness: SourceCompleteness
    proceeding_nature: ProceedingNature | None = None
    ceo_reference_warning: str | None = None


class EditorialPreviewResponse(EditorialPreviewBanner):
    politician_id: int
    politician_name: str
    biography: EditorialPreviewBiography | None = None
    career_entries: tuple[EditorialPreviewCareerEntry, ...] = ()
    positions: tuple[EditorialPreviewPosition, ...] = ()
    proceedings: tuple[EditorialPreviewProceeding, ...] = ()
    pending_counts: dict[str, int] = Field(default_factory=dict)
