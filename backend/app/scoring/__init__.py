"""Pledge classification, fulfilment scoring and its validation.

Pure algorithms only (no database access). Services in
``backend.app.services.pledge_service`` and
``backend.app.services.pledge_evidence_service`` connect them to the models.
See ``docs/scoring-methodology.md``.
"""

from backend.app.scoring.agreement import AlphaMetric, AlphaResult, krippendorff_alpha
from backend.app.scoring.audit_correction import (
    AuditSample,
    CorrectedEstimate,
    design_based_mean,
    draw_audit_sample,
)
from backend.app.scoring.bias_audit import (
    BiasAuditReport,
    BiasObservation,
    BlocComparison,
    partisan_skew_audit,
)
from backend.app.scoring.scorecard import (
    DEFAULT_METHODOLOGY,
    METHODOLOGY_VERSION,
    MandateProgress,
    PledgeOutcome,
    RoleStratum,
    Scorecard,
    ScoringMethodology,
    compute_scorecard,
)
from backend.app.scoring.types import (
    CLOSED_VERDICTS,
    CommitmentType,
    DUAL_APPROVAL_VERDICTS,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    OPEN_VERDICTS,
    PledgeSpecificity,
    VERDICT_VALUE,
)

__all__ = [
    "AlphaMetric",
    "AlphaResult",
    "AuditSample",
    "BiasAuditReport",
    "BiasObservation",
    "BlocComparison",
    "CLOSED_VERDICTS",
    "CommitmentType",
    "CorrectedEstimate",
    "DEFAULT_METHODOLOGY",
    "DUAL_APPROVAL_VERDICTS",
    "EvidenceLabel",
    "FulfillmentVerdict",
    "HolderRole",
    "METHODOLOGY_VERSION",
    "MandateProgress",
    "OPEN_VERDICTS",
    "PledgeOutcome",
    "PledgeSpecificity",
    "RoleStratum",
    "Scorecard",
    "ScoringMethodology",
    "VERDICT_VALUE",
    "compute_scorecard",
    "design_based_mean",
    "draw_audit_sample",
    "krippendorff_alpha",
    "partisan_skew_audit",
]
