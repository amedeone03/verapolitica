from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from backend.app.models import (
    ProposalActorRole,
    ProposalActorType,
    ProposalDraftKind,
    ProposalDraftStatus,
    ProposalReviewDecision,
    ProposalStatus,
    ProposalType,
)
from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.ai_extraction import (
    AbstentionReason,
    ModelConfidence,
    PoliticalTopic,
)


class ObservedActorType(StrEnum):
    POLITICIAN = "politician"
    POLITICAL_PARTY = "political_party"
    INSTITUTION = "institution"
    UNRESOLVED = "unresolved"


class ProposalActorObservation(ImmutableSchema):
    actor_type: ObservedActorType
    role: ProposalActorRole
    display_name: str = Field(min_length=1, max_length=500)
    authority_key: str | None = Field(default=None, min_length=1, max_length=100)
    source_identifier: str | None = Field(default=None, min_length=1, max_length=1000)
    institution_name: str | None = Field(default=None, min_length=1, max_length=500)
    source_field: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_identity(self) -> "ProposalActorObservation":
        if self.actor_type in (
            ObservedActorType.POLITICIAN,
            ObservedActorType.POLITICAL_PARTY,
        ) and (self.authority_key is None or self.source_identifier is None):
            raise ValueError("canonical actors require an authority and source identifier")
        if (
            self.actor_type is ObservedActorType.INSTITUTION
            and self.institution_name is None
        ):
            raise ValueError("institution actors require institution_name")
        return self


class ProposalEvidenceObservation(ImmutableSchema):
    field_path: str = Field(min_length=1, max_length=500)
    source_url: AnyHttpUrl
    source_field: str = Field(min_length=1, max_length=500)
    source_value: str = Field(min_length=1)


class ProposalObservation(ImmutableSchema):
    """Source-independent, transient official proposal assertion."""

    source_key: str = Field(min_length=1, max_length=100)
    raw_document_id: int = Field(gt=0)
    proposal_identifier: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=1000)
    summary: str | None = None
    exact_statement: str | None = None
    proposal_type: ProposalType
    introduced_at: date | None = None
    source_status_label: str = Field(min_length=1, max_length=500)
    normalized_status: ProposalStatus
    status_effective_at: date | None = None
    status_source_identifier: str | None = Field(
        default=None, min_length=1, max_length=1000
    )
    official_url: AnyHttpUrl
    status_url: AnyHttpUrl | None = None
    source_field: str = Field(min_length=1, max_length=500)
    observed_at: datetime
    actors: tuple[ProposalActorObservation, ...] = ()
    evidence: tuple[ProposalEvidenceObservation, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_semantics(self) -> "ProposalObservation":
        if (
            self.introduced_at is not None
            and self.status_effective_at is not None
            and self.status_effective_at < self.introduced_at
        ):
            raise ValueError("status_effective_at cannot predate introduced_at")
        if self.proposal_type is ProposalType.EXPLICIT_PROMISE:
            if not self.exact_statement or not self.exact_statement.strip():
                raise ValueError("an explicit promise requires its exact statement")
            if not any(
                actor.role is ProposalActorRole.COMMITMENT_OWNER
                for actor in self.actors
            ):
                raise ValueError("an explicit promise requires a commitment owner")
        if not self.evidence:
            raise ValueError("proposal observations require official evidence")
        return self


class ProposalSyncDisposition(StrEnum):
    DRAFT_CREATED = "draft_created"
    ALREADY_OBSERVED = "already_observed"


class ProposalSyncDetail(ImmutableSchema):
    proposal_id: int = Field(gt=0)
    draft_id: int | None = Field(default=None, gt=0)
    proposal_identifier: str
    title: str
    disposition: ProposalSyncDisposition
    unresolved_actors: tuple[str, ...] = ()


class ProposalSyncResult(ImmutableSchema):
    total_observations: int = Field(ge=0)
    proposals_created: int = Field(ge=0)
    drafts_created: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    resolved_actors: int = Field(ge=0)
    unresolved_actors: int = Field(ge=0)
    details: tuple[ProposalSyncDetail, ...]


class ProposalReviewStarted(ImmutableSchema):
    draft_id: int = Field(gt=0)
    proposal_id: int = Field(gt=0)
    final_draft_status: ProposalDraftStatus


class ProposalReviewResult(ImmutableSchema):
    review_id: int = Field(gt=0)
    draft_id: int = Field(gt=0)
    proposal_id: int = Field(gt=0)
    decision: ProposalReviewDecision
    final_draft_status: ProposalDraftStatus
    created_status_event_id: int | None = Field(default=None, gt=0)


class ProposalAdminSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposalEvidenceResponse(ProposalAdminSchema):
    id: int
    field_path: str
    source_name: str
    source_url: str
    source_field: str
    source_value: str
    observed_at: datetime


class ProposalDraftListItem(ProposalAdminSchema):
    id: int
    proposal_id: int
    title: str
    proposal_type: ProposalType
    kind: ProposalDraftKind
    status: ProposalDraftStatus
    normalized_status: ProposalStatus
    source_status_label: str
    created_at: datetime
    evidence_count: int
    unresolved_actor_count: int


class ProposalDraftListResponse(ProposalAdminSchema):
    items: tuple[ProposalDraftListItem, ...]
    total: int
    offset: int
    limit: int


class ProposalFinalReviewResponse(ProposalAdminSchema):
    id: int
    reviewer: str
    decision: ProposalReviewDecision
    note: str | None
    created_at: datetime


class AIProposalEvidenceResponse(ProposalAdminSchema):
    chunk_index: int
    page: int | None
    supporting_text: str
    source_url: str


class AIProposalAssistanceResponse(ProposalAdminSchema):
    extraction_run_id: int
    raw_document_id: int
    source_document_url: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    confidence: ModelConfidence | None
    topic: PoliticalTopic | None
    abstention_reason: AbstentionReason | None
    evidence: tuple[AIProposalEvidenceResponse, ...]


class ProposalDraftDetailResponse(ProposalAdminSchema):
    id: int
    proposal_id: int
    kind: ProposalDraftKind
    status: ProposalDraftStatus
    baseline_status_event_id: int | None
    supersedes_id: int | None
    proposed: ProposalObservation
    evidence: tuple[ProposalEvidenceResponse, ...]
    ai_assistance: AIProposalAssistanceResponse | None = None
    final_review: ProposalFinalReviewResponse | None
    created_at: datetime
    updated_at: datetime


class PublicProposalSource(ImmutableSchema):
    name: str
    url: AnyHttpUrl


class PublicProposalActor(ImmutableSchema):
    actor_type: ProposalActorType
    role: ProposalActorRole
    display_name: str
    politician_id: int | None = None


class PublicProposalStatusEvent(ImmutableSchema):
    status: ProposalStatus
    source_status_label: str
    effective_at: date | None
    source: PublicProposalSource


class PublicProposalSummary(ImmutableSchema):
    id: int = Field(gt=0)
    title: str
    proposal_type: ProposalType
    introduced_at: date | None
    current_status: ProposalStatus
    actors: tuple[PublicProposalActor, ...]
    source: PublicProposalSource


class PublicProposal(PublicProposalSummary):
    summary: str | None
    exact_statement: str | None
    status_history: tuple[PublicProposalStatusEvent, ...]
    sources: tuple[PublicProposalSource, ...]
    published_at: datetime


class PublicProposalList(ImmutableSchema):
    items: tuple[PublicProposalSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class PublicPoliticianProposal(ImmutableSchema):
    id: int
    title: str
    proposal_type: ProposalType
    current_status: ProposalStatus
    role: ProposalActorRole
    introduced_at: date | None
