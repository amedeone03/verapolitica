from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.models import ProposalActorRole
from backend.app.schemas.ai_extraction import (
    AbstentionReason,
    ExtractedClaimType,
    ExtractedPoliticalClaim,
    PoliticalTopic,
)


EVALUATOR_VERSION = "ai_evaluator_v1"
MATCHER_VERSION = "claim_matcher_v1"
NORMALIZER_VERSION = "evaluation_normalizer_v1"


class EvaluationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvaluationRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class EvaluationCaseStatus(StrEnum):
    COMPLETED = "completed"
    PROVIDER_FAILED = "provider_failed"
    SCHEMA_FAILED = "schema_failed"
    EXTRACTION_FAILED = "extraction_failed"


class GoldActor(EvaluationSchema):
    name: str = Field(min_length=1, max_length=500)
    role: ProposalActorRole


class GoldEvidence(EvaluationSchema):
    chunk_index: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    supporting_text: str = Field(min_length=1, max_length=2_000)


class GoldNumericCommitment(EvaluationSchema):
    value: str = Field(pattern=r"^\d+(?:\.\d+)?$")
    unit: str = Field(min_length=1, max_length=100)


class GoldClaim(EvaluationSchema):
    claim_id: str = Field(min_length=1, max_length=100)
    claim_type: ExtractedClaimType
    exact_statement: str = Field(min_length=1, max_length=2_000)
    normalized_title: str = Field(min_length=1, max_length=1_000)
    actors: tuple[GoldActor, ...] = ()
    topic: PoliticalTopic | None = None
    announced_at: date | None = None
    target_date: date | None = None
    numeric_commitments: tuple[GoldNumericCommitment, ...] = ()
    evidence: tuple[GoldEvidence, ...] = ()
    notes: str | None = None


class GoldExtractionCase(EvaluationSchema):
    case_id: str = Field(min_length=1, max_length=100)
    document: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    synthetic: bool
    expects_abstention: bool = False
    abstention_reason: AbstentionReason | None = None
    claims: tuple[GoldClaim, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def validate_expectation(self) -> "GoldExtractionCase":
        if self.expects_abstention and self.claims:
            raise ValueError("abstention cases cannot contain expected claims")
        if not self.expects_abstention and not self.claims:
            raise ValueError("answerable cases require at least one expected claim")
        if self.abstention_reason is not None and not self.expects_abstention:
            raise ValueError("abstention_reason requires expects_abstention")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique within a case")
        return self


class GoldEvaluationDataset(EvaluationSchema):
    dataset_version: str = Field(min_length=1, max_length=100)
    description: str
    prompt_version: str
    schema_version: str
    max_chunk_chars: int = Field(default=4_000, ge=100, le=20_000)
    max_chunks: int = Field(default=40, ge=1, le=200)
    cases: tuple[GoldExtractionCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "GoldEvaluationDataset":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case IDs must be unique")
        return self


class ClaimMatch(EvaluationSchema):
    prediction_index: int = Field(ge=0)
    gold_claim_id: str | None = None
    method: str
    ambiguous_gold_claim_ids: tuple[str, ...] = ()


class CaseMetricCounts(EvaluationSchema):
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    type_correct: int = Field(ge=0)
    type_total: int = Field(ge=0)
    evidence_correct: int = Field(ge=0)
    evidence_wrong: int = Field(ge=0)
    evidence_missing: int = Field(ge=0)
    actor_true_positives: int = Field(ge=0)
    actor_false_positives: int = Field(ge=0)
    actor_false_negatives: int = Field(ge=0)
    topic_correct: int = Field(ge=0)
    topic_total: int = Field(ge=0)
    date_correct: int = Field(ge=0)
    date_total: int = Field(ge=0)
    numeric_correct: int = Field(ge=0)
    numeric_total: int = Field(ge=0)
    unsupported_predictions: int = Field(ge=0)


class EvaluationCaseResult(EvaluationSchema):
    case_id: str
    status: EvaluationCaseStatus
    expected_claims: tuple[GoldClaim, ...]
    predicted_claims: tuple[ExtractedPoliticalClaim, ...] = ()
    matches: tuple[ClaimMatch, ...] = ()
    false_positive_indexes: tuple[int, ...] = ()
    false_negative_claim_ids: tuple[str, ...] = ()
    claim_type_errors: tuple[str, ...] = ()
    evidence_errors: tuple[str, ...] = ()
    actor_errors: tuple[str, ...] = ()
    topic_errors: tuple[str, ...] = ()
    predicted_abstention: bool
    abstention_correct: bool
    counts: CaseMetricCounts
    error: str | None = None


class ClassMetrics(EvaluationSchema):
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    false_negatives: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)


class EvaluationMetrics(EvaluationSchema):
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    claim_type_accuracy: float
    claim_type_metrics: dict[str, ClassMetrics]
    claim_type_confusion: dict[str, dict[str, int]]
    evidence_accuracy: float
    grounded_correctly: int
    wrong_evidence: int
    missing_evidence: int
    actor_precision: float
    actor_recall: float
    actor_f1: float
    topic_accuracy: float
    topic_counts: dict[str, dict[str, int]]
    date_accuracy: float
    date_field_accuracy: dict[str, float]
    numeric_accuracy: float
    abstention_accuracy: float
    abstention_precision: float
    abstention_recall: float
    correct_abstentions: int
    incorrect_abstentions: int
    missed_abstentions: int
    inappropriate_claim_generations: int
    hallucination_rate: float
    failed_cases: int


class EvaluationThresholds(EvaluationSchema):
    min_precision: float = Field(default=0.90, ge=0, le=1)
    min_evidence_accuracy: float = Field(default=0.95, ge=0, le=1)
    max_hallucination_rate: float = Field(default=0.05, ge=0, le=1)


class ThresholdResult(EvaluationSchema):
    passed: bool
    failures: tuple[str, ...] = ()


class EvaluationUsage(EvaluationSchema):
    request_count: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class EvaluationReport(EvaluationSchema):
    run_id: int | None = None
    dataset_version: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    evaluator_version: str = EVALUATOR_VERSION
    matcher_version: str = MATCHER_VERSION
    normalizer_version: str = NORMALIZER_VERSION
    started_at: datetime
    completed_at: datetime
    status: EvaluationRunStatus
    case_count: int
    metrics: EvaluationMetrics
    thresholds: EvaluationThresholds
    threshold_result: ThresholdResult
    usage: EvaluationUsage
    case_results: tuple[EvaluationCaseResult, ...]
    error_summary: tuple[str, ...] = ()


class EvaluationComparison(EvaluationSchema):
    run_a: dict[str, str]
    run_b: dict[str, str]
    metric_deltas: dict[str, float]
