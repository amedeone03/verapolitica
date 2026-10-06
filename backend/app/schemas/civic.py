from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from backend.app.models.civic import (
    GeographicScopeType,
    NotificationEventType,
    ReferendumDraftKind,
    ReferendumDraftStatus,
    ReferendumReviewDecision,
    ReferendumStatus,
    ReferendumType,
    VotingGuideSectionKey,
)
from backend.app.schemas.candidate_profile import ImmutableSchema


class ReferendumEvidenceObservation(ImmutableSchema):
    field_path: str = Field(min_length=1, max_length=500)
    source_url: AnyHttpUrl
    source_field: str = Field(min_length=1, max_length=500)
    source_value: str = Field(min_length=1)


class ReferendumObservation(ImmutableSchema):
    source_key: str = Field(min_length=1, max_length=100)
    raw_document_id: int = Field(gt=0)
    official_identifier: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=1000)
    official_question: str = Field(min_length=1)
    referendum_type: ReferendumType
    status: ReferendumStatus
    vote_date: date
    vote_end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    voting_hours_description: str | None = None
    scope_type: GeographicScopeType
    region_istat_code: str | None = Field(default=None, min_length=2, max_length=2)
    municipality_istat_code: str | None = Field(default=None, min_length=6, max_length=6)
    quorum_required: bool | None = None
    quorum_description: str | None = None
    official_source_url: AnyHttpUrl
    is_synthetic: bool = False
    observed_at: datetime
    evidence: tuple[ReferendumEvidenceObservation, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope_and_evidence(self) -> "ReferendumObservation":
        if not self.evidence:
            raise ValueError("referendum observations require official evidence")
        if self.scope_type is GeographicScopeType.NATIONAL and (
            self.region_istat_code or self.municipality_istat_code
        ):
            raise ValueError("national referendums must not bind a territory")
        if self.scope_type is GeographicScopeType.REGION and not self.region_istat_code:
            raise ValueError("regional referendums require a region ISTAT code")
        if (
            self.scope_type is GeographicScopeType.MUNICIPALITY
            and not self.municipality_istat_code
        ):
            raise ValueError("municipal referendums require a municipality ISTAT code")
        if self.vote_end_date is not None and self.vote_end_date < self.vote_date:
            raise ValueError("vote_end_date cannot predate vote_date")
        return self


class ReferendumSyncDisposition(StrEnum):
    DRAFT_CREATED = "draft_created"
    ALREADY_OBSERVED = "already_observed"


class ReferendumSyncDetail(ImmutableSchema):
    referendum_id: int = Field(gt=0)
    draft_id: int | None = Field(default=None, gt=0)
    official_identifier: str
    title: str
    disposition: ReferendumSyncDisposition


class ReferendumSyncResult(ImmutableSchema):
    details: tuple[ReferendumSyncDetail, ...]
    created: int = Field(ge=0)
    already_observed: int = Field(ge=0)


class ReferendumReviewStarted(ImmutableSchema):
    draft_id: int = Field(gt=0)
    referendum_id: int = Field(gt=0)
    final_draft_status: ReferendumDraftStatus


class ReferendumReviewResult(ImmutableSchema):
    review_id: int = Field(gt=0)
    draft_id: int = Field(gt=0)
    referendum_id: int = Field(gt=0)
    decision: ReferendumReviewDecision
    final_draft_status: ReferendumDraftStatus
    published: bool = False


class ReferendumEvidenceResponse(ImmutableSchema):
    id: int = Field(gt=0)
    field_path: str
    source_name: str
    source_url: str
    source_field: str
    source_value: str
    observed_at: datetime


class ReferendumFinalReviewResponse(ImmutableSchema):
    id: int = Field(gt=0)
    reviewer: str
    decision: ReferendumReviewDecision
    note: str | None = None
    created_at: datetime


class ReferendumDraftListItem(ImmutableSchema):
    id: int = Field(gt=0)
    referendum_id: int = Field(gt=0)
    title: str
    referendum_type: ReferendumType
    kind: ReferendumDraftKind
    status: ReferendumDraftStatus
    vote_date: date
    created_at: datetime
    evidence_count: int = Field(ge=0)


class ReferendumDraftListResponse(ImmutableSchema):
    items: tuple[ReferendumDraftListItem, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class ReferendumDraftDetailResponse(ImmutableSchema):
    id: int = Field(gt=0)
    referendum_id: int = Field(gt=0)
    kind: ReferendumDraftKind
    status: ReferendumDraftStatus
    supersedes_id: int | None = None
    proposed: ReferendumObservation
    evidence: tuple[ReferendumEvidenceResponse, ...]
    final_review: ReferendumFinalReviewResponse | None = None
    created_at: datetime
    updated_at: datetime


class PublicReferendumSource(ImmutableSchema):
    source_name: str
    official_identifier: str
    source_url: str


class PublicReferendumSummary(ImmutableSchema):
    id: int = Field(gt=0)
    title: str
    referendum_type: ReferendumType
    status: ReferendumStatus
    vote_date: date
    scope_type: GeographicScopeType
    region_name: str | None = None
    municipality_name: str | None = None
    official_source_url: str
    is_synthetic: bool = False


class PublicReferendum(PublicReferendumSummary):
    official_question: str
    vote_end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    voting_hours_description: str | None = None
    quorum_required: bool | None = None
    quorum_description: str | None = None
    voting_guide_id: int | None = None
    sources: tuple[PublicReferendumSource, ...] = ()


class PublicReferendumList(ImmutableSchema):
    items: tuple[PublicReferendumSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class VotingGuideSection(ImmutableSchema):
    key: VotingGuideSectionKey
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    source_url: AnyHttpUrl | None = None


class PublicVotingGuide(ImmutableSchema):
    id: int = Field(gt=0)
    title: str
    scope: GeographicScopeType
    sections: tuple[VotingGuideSection, ...]
    valid_from: date | None = None
    valid_until: date | None = None
    source_url: str
    source_name: str
    is_synthetic: bool = False


class PublicVotingGuideList(ImmutableSchema):
    items: tuple[PublicVotingGuide, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class PublicGlossaryTermSummary(ImmutableSchema):
    slug: str
    term: str
    short_definition: str
    source_url: str
    extended_definition: str | None = None


class PublicGlossaryTerm(PublicGlossaryTermSummary):
    source_name: str
    is_synthetic: bool = False


class PublicGlossaryList(ImmutableSchema):
    items: tuple[PublicGlossaryTermSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)


class ReminderCandidateResult(ImmutableSchema):
    created: int = Field(ge=0)
    already_present: int = Field(ge=0)
    referendum_ids: tuple[int, ...] = ()


class NotificationSubscriptionResult(ImmutableSchema):
    id: int = Field(gt=0)
    channel: str
    event_type: NotificationEventType
    referendum_id: int | None = None
    enabled: bool


class GlossaryTermInput(ImmutableSchema):
    slug: str = Field(min_length=1, max_length=200)
    term: str = Field(min_length=1, max_length=300)
    short_definition: str = Field(min_length=1)
    extended_definition: str | None = None
    source_url: AnyHttpUrl
    source_key: str = Field(min_length=1, max_length=100)
    is_synthetic: bool = False
    publish: bool = False

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        slug = value.strip().casefold().replace(" ", "-")
        if not slug.replace("-", "").isalnum():
            raise ValueError("slug must be alphanumeric with hyphens")
        return slug


class VotingGuideInput(ImmutableSchema):
    title: str = Field(min_length=1, max_length=500)
    scope: GeographicScopeType
    sections: tuple[VotingGuideSection, ...]
    source_url: AnyHttpUrl
    source_key: str = Field(min_length=1, max_length=100)
    valid_from: date | None = None
    valid_until: date | None = None
    is_synthetic: bool = False
    publish: bool = False

    @model_validator(mode="after")
    def validate_sections(self) -> "VotingGuideInput":
        if not self.sections:
            raise ValueError("voting guides require at least one official section")
        keys = [item.key for item in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("voting guide section keys must be unique")
        return self
