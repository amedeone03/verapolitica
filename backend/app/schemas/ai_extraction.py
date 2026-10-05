from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models import ProposalActorRole


AI_EXTRACTION_SCHEMA_VERSION = "proposal_claim_schema_v1"


class StrictExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedClaimType(StrEnum):
    PROPOSAL = "proposal"
    EXPLICIT_PROMISE = "explicit_promise"


class PoliticalTopic(StrEnum):
    ECONOMY = "economy"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    ENVIRONMENT = "environment"
    HOUSING = "housing"
    TRANSPORT = "transport"
    JUSTICE = "justice"
    IMMIGRATION = "immigration"
    FOREIGN_POLICY = "foreign_policy"
    PUBLIC_ADMINISTRATION = "public_administration"
    OTHER = "other"


class ModelConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AbstentionReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    AMBIGUOUS_ACTOR = "ambiguous_actor"
    UNCLEAR_COMMITMENT = "unclear_commitment"
    INCOMPLETE_CONTEXT = "incomplete_context"
    UNSUPPORTED_DOCUMENT_CONTENT = "unsupported_document_content"


class ExtractedActorMention(StrictExtractionSchema):
    name: str = Field(min_length=1, max_length=500)
    role: ProposalActorRole


class ExtractedClaimEvidence(StrictExtractionSchema):
    chunk_index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    supporting_text: str = Field(min_length=1, max_length=2_000)


class ExtractedPoliticalClaim(StrictExtractionSchema):
    claim_type: ExtractedClaimType | None = None
    exact_statement: str | None = Field(default=None, min_length=1, max_length=2_000)
    normalized_title: str | None = Field(default=None, min_length=1, max_length=1_000)
    summary: str | None = Field(default=None, max_length=2_000)
    topic: PoliticalTopic | None = None
    actor_mentions: tuple[ExtractedActorMention, ...] = ()
    announced_at: date | None = None
    target_date: date | None = None
    evidence: tuple[ExtractedClaimEvidence, ...] = ()
    confidence: ModelConfidence | None = None
    abstention_reason: AbstentionReason | None = None

    @model_validator(mode="after")
    def validate_claim_or_abstention(self) -> "ExtractedPoliticalClaim":
        if self.abstention_reason is not None:
            return self
        missing = [
            name
            for name, value in (
                ("claim_type", self.claim_type),
                ("exact_statement", self.exact_statement),
                ("normalized_title", self.normalized_title),
                ("confidence", self.confidence),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "non-abstaining claims require " + ", ".join(missing)
            )
        if not self.evidence:
            raise ValueError("non-abstaining claims require evidence")
        if self.claim_type is ExtractedClaimType.EXPLICIT_PROMISE and not any(
            actor.role is ProposalActorRole.COMMITMENT_OWNER
            for actor in self.actor_mentions
        ):
            raise ValueError(
                "an explicit promise requires an explicit commitment-owner mention"
            )
        if (
            self.announced_at is not None
            and self.target_date is not None
            and self.target_date < self.announced_at
        ):
            raise ValueError("target_date cannot predate announced_at")
        return self


class PoliticalClaimExtraction(StrictExtractionSchema):
    candidates: tuple[ExtractedPoliticalClaim, ...]


class ProviderUsage(StrictExtractionSchema):
    request_count: int = Field(default=1, ge=1)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class StructuredExtractionResult(StrictExtractionSchema):
    output: PoliticalClaimExtraction
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    provider_response_id: str | None = Field(default=None, max_length=500)
