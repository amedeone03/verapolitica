from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class PledgeClassificationRequest(_Frozen):
    specificity: PledgeSpecificity
    commitment_type: CommitmentType
    holder_role: HolderRole
    cap_topic_code: str | None = Field(default=None, max_length=16, pattern=r"^[0-9]{1,4}$")
    mandate_start: date | None = None
    mandate_end: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class PledgeClassificationResponse(_Frozen):
    proposal_id: int
    specificity: PledgeSpecificity
    commitment_type: CommitmentType
    holder_role: HolderRole
    cap_topic_code: str | None
    mandate_start: date | None
    mandate_end: date | None
    included_in_score: bool
    classified_by: str
    updated_at: datetime


class PledgeAssessmentProposal(_Frozen):
    """An editor-proposed verdict. The excerpt must be verbatim in the source."""

    verdict: FulfillmentVerdict
    evidence_label: EvidenceLabel
    rationale: str = Field(min_length=1, max_length=4000)
    quoted_excerpt: str = Field(min_length=12, max_length=4000)
    raw_document_id: int = Field(gt=0)
    document_chunk_id: int | None = Field(default=None, gt=0)
    effective_at: date | None = None

    @field_validator("rationale", "quoted_excerpt")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class PledgeApprovalRequest(_Frozen):
    note: str | None = Field(default=None, max_length=2000)


class PledgeRejectionRequest(_Frozen):
    note: str = Field(min_length=1, max_length=2000)


class PledgeAssessmentDraftResponse(_Frozen):
    id: int
    proposal_id: int
    origin: str
    status: str
    proposed_verdict: FulfillmentVerdict
    evidence_label: EvidenceLabel
    rationale: str
    quoted_excerpt: str
    source_url: str
    raw_document_id: int
    document_chunk_id: int | None
    effective_at: date | None
    approvals: tuple[str, ...]
    approvals_required: int
    judge_name: str | None
    judge_version: str | None
    created_by: str
    created_at: datetime


class PledgeAssessmentResponse(_Frozen):
    id: int
    proposal_id: int
    verdict: FulfillmentVerdict
    rationale: str
    quoted_excerpt: str
    source_url: str
    effective_at: date | None
    methodology_version: str
    created_at: datetime


class CompositionEntry(_Frozen):
    verdict: FulfillmentVerdict
    count: int


class TopicEntry(_Frozen):
    cap_topic_code: str
    count: int


class ScorecardStratumResponse(_Frozen):
    role: HolderRole
    composition: tuple[CompositionEntry, ...]
    scored_pledges: int
    closed_pledges: int
    open_pledges: int
    kept_equivalent: float
    rate: float | None
    credible_interval: tuple[float, float] | None
    rate_withheld_reason: str | None
    topics: tuple[TopicEntry, ...]


class MandateProgressResponse(_Frozen):
    start: date
    end: date
    as_of: date
    elapsed_fraction: float


class PublicScorecardPledge(_Frozen):
    proposal_id: int
    title: str
    exact_statement: str | None
    verdict: FulfillmentVerdict
    role: HolderRole
    specificity: PledgeSpecificity
    commitment_type: CommitmentType
    cap_topic_code: str | None
    included_in_score: bool
    latest_assessment: PledgeAssessmentResponse | None


class PublicScorecard(_Frozen):
    """Order matters for clients: pledges, then composition, then the rate."""

    politician_id: int
    methodology_version: str
    methodology_url: str
    as_of: date
    pledges: tuple[PublicScorecardPledge, ...]
    tracked_pledges: int
    unclassified_pledges: int
    excluded_vague_pledges: int
    credible_level: float
    min_closed_for_rate: int
    mandate_progress: MandateProgressResponse | None
    strata: tuple[ScorecardStratumResponse, ...]


class AuditSampleRequest(_Frozen):
    sample_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    size: int = Field(gt=0, le=10_000)
    seed: int


class BlindAuditItem(_Frozen):
    """What an auditor sees: the pledge and the source, never the published verdict."""

    assessment_id: int
    proposal_id: int
    title: str
    exact_statement: str | None
    commitment_type: CommitmentType
    quoted_excerpt: str
    source_url: str


class AuditSampleResponse(_Frozen):
    sample_key: str
    seed: int
    population_size: int
    inclusion_probability: float
    items: tuple[BlindAuditItem, ...]


class AuditCodingRequest(_Frozen):
    verdict: FulfillmentVerdict
    coder: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class AgreementResponse(_Frozen):
    metric: str
    alpha: float | None
    pairable_units: int


class CorrectedRateResponse(_Frozen):
    role: HolderRole
    naive_rate: float | None
    corrected_rate: float | None
    standard_error: float | None
    confidence_interval: tuple[float, float] | None
    population_size: int
    audited: int
    disagreement_rate: float | None


class AuditQualityReport(_Frozen):
    sample_key: str
    coded_items: int
    nominal_agreement: AgreementResponse
    ordinal_agreement: AgreementResponse
    corrected_rates: tuple[CorrectedRateResponse, ...]


class BlocComparisonResponse(_Frozen):
    bloc: str
    stratum_count: int
    bloc_pledges: int
    other_pledges: int
    weighted_difference: float | None
    confidence_interval: tuple[float, float] | None
    flagged: bool


class BiasAuditResponse(_Frozen):
    methodology_version: str
    min_per_group: int
    flag_threshold: float
    skipped_strata: int
    comparisons: tuple[BlocComparisonResponse, ...]
