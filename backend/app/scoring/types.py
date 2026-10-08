"""Shared vocabulary for pledge classification, fulfilment and scoring.

The categories follow the pledge-research literature the methodology is built on:

* Royed (1996): only a specific, verifiable commitment is a pledge. Vague
  rhetoric is stored but never scored (``PledgeSpecificity.VAGUE``).
* Thomson et al. (2017, Comparative Party Pledges Group): fulfilment is coded as
  fulfilled / partially fulfilled / not fulfilled, and pledges about an *action*
  are verified differently from pledges about an *outcome*.
* FEVER (Thorne et al., 2018): evidence either supports, refutes, or is not
  enough to decide. "Not enough info" is the default and never changes a verdict.

This module has no ORM imports so the algorithms stay testable in isolation.
"""

from enum import StrEnum


class PledgeSpecificity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    VAGUE = "vague"


class CommitmentType(StrEnum):
    """Royed/CPPG distinction: what would count as fulfilment."""

    ACTION = "action"  # "presenterò una legge su..." -> verified with official acts
    OUTCOME = "outcome"  # "ridurrò la disoccupazione" -> verified with statistics


class HolderRole(StrEnum):
    """Role of the commitment owner when the pledge was made.

    Fulfilment depends on institutional power more than on anything else, so
    scores are only ever computed and shown within one role.
    """

    GOVERNMENT_SINGLE_PARTY = "government_single_party"
    GOVERNMENT_COALITION = "government_coalition"
    OPPOSITION = "opposition"
    UNKNOWN = "unknown"


class FulfillmentVerdict(StrEnum):
    NOT_YET_RATED = "not_yet_rated"
    IN_PROGRESS = "in_progress"
    STALLED = "stalled"
    KEPT = "kept"
    PARTIALLY_KEPT = "partially_kept"
    BROKEN = "broken"


class EvidenceLabel(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    NOT_ENOUGH_INFO = "not_enough_info"


CLOSED_VERDICTS: frozenset[FulfillmentVerdict] = frozenset(
    {
        FulfillmentVerdict.KEPT,
        FulfillmentVerdict.PARTIALLY_KEPT,
        FulfillmentVerdict.BROKEN,
    }
)
OPEN_VERDICTS: frozenset[FulfillmentVerdict] = frozenset(
    set(FulfillmentVerdict) - CLOSED_VERDICTS
)

# Verdicts whose publication requires two distinct reviewers.
DUAL_APPROVAL_VERDICTS: frozenset[FulfillmentVerdict] = frozenset(
    {FulfillmentVerdict.BROKEN}
)

# Which fulfilment verdicts an evidence label may propose.
VERDICTS_BY_EVIDENCE_LABEL: dict[EvidenceLabel, frozenset[FulfillmentVerdict]] = {
    EvidenceLabel.SUPPORTS: frozenset(
        {
            FulfillmentVerdict.KEPT,
            FulfillmentVerdict.PARTIALLY_KEPT,
            FulfillmentVerdict.IN_PROGRESS,
        }
    ),
    EvidenceLabel.REFUTES: frozenset(
        {FulfillmentVerdict.BROKEN, FulfillmentVerdict.STALLED}
    ),
    EvidenceLabel.NOT_ENOUGH_INFO: frozenset(),
}

# Numeric value of a closed verdict, used by the score, the audit correction and
# the bias audit. "Partially kept" counts half, as in the original specification.
VERDICT_VALUE: dict[FulfillmentVerdict, float] = {
    FulfillmentVerdict.KEPT: 1.0,
    FulfillmentVerdict.PARTIALLY_KEPT: 0.5,
    FulfillmentVerdict.BROKEN: 0.0,
}

# Ordinal order used for Krippendorff's alpha on closed verdicts.
CLOSED_VERDICT_ORDER: tuple[FulfillmentVerdict, ...] = (
    FulfillmentVerdict.BROKEN,
    FulfillmentVerdict.PARTIALLY_KEPT,
    FulfillmentVerdict.KEPT,
)

# Display order for the composition bar (Naurin 2011: composition before the number).
COMPOSITION_ORDER: tuple[FulfillmentVerdict, ...] = (
    FulfillmentVerdict.KEPT,
    FulfillmentVerdict.PARTIALLY_KEPT,
    FulfillmentVerdict.BROKEN,
    FulfillmentVerdict.IN_PROGRESS,
    FulfillmentVerdict.STALLED,
    FulfillmentVerdict.NOT_YET_RATED,
)
