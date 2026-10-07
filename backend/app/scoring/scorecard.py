"""Pledge scorecard ("pagella") — methodology ``pledge-score/v1``.

The base formula from the product specification is kept::

    rate = (kept + 0.5 * partially_kept) / closed

with three corrections that the pledge-fulfilment literature makes necessary:

1. **Role first.** Fulfilment depends mostly on institutional power (Thomson et
   al. 2017): single-party government > coalition government > opposition. A
   scorecard is therefore a list of role strata, and there is deliberately no
   number that mixes them.
2. **Closed pledges only.** Mid-term, most pledges are still open. Only kept,
   partially kept and broken pledges enter the denominator; open pledges are
   reported separately, next to the elapsed share of the mandate.
3. **Small numbers.** With few closed pledges the raw rate is noise. Every
   stratum reports a beta-binomial credible interval (Jeffreys prior), and the
   rate itself is withheld below ``min_closed_for_rate`` closed pledges.

Vague pledges (Royed 1996) are tracked but excluded from every count used by
the score. The output lists the composition before the rate, which is the order
the frontend must respect (Naurin 2011: perception is worse than the data, and
a lone percentage amplifies that).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from backend.app.scoring.beta import beta_equal_tailed_interval
from backend.app.scoring.types import (
    CLOSED_VERDICTS,
    COMPOSITION_ORDER,
    CommitmentType,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
    VERDICT_VALUE,
)

METHODOLOGY_VERSION = "pledge-score/v1"


@dataclass(frozen=True, slots=True)
class ScoringMethodology:
    version: str = METHODOLOGY_VERSION
    partial_weight: float = VERDICT_VALUE[FulfillmentVerdict.PARTIALLY_KEPT]
    min_closed_for_rate: int = 8
    prior_alpha: float = 0.5  # Jeffreys prior
    prior_beta: float = 0.5
    credible_level: float = 0.90

    def __post_init__(self) -> None:
        if not 0.0 <= self.partial_weight <= 1.0:
            raise ValueError("partial_weight must be within [0, 1]")
        if self.min_closed_for_rate < 1:
            raise ValueError("min_closed_for_rate must be positive")
        if self.prior_alpha <= 0 or self.prior_beta <= 0:
            raise ValueError("prior parameters must be positive")


DEFAULT_METHODOLOGY = ScoringMethodology()


@dataclass(frozen=True, slots=True)
class PledgeOutcome:
    """One tracked pledge with its current approved verdict."""

    pledge_id: int
    verdict: FulfillmentVerdict
    role: HolderRole
    specificity: PledgeSpecificity
    commitment_type: CommitmentType
    topic_code: str | None = None


@dataclass(frozen=True, slots=True)
class MandateProgress:
    start: date
    end: date
    as_of: date

    @property
    def elapsed_fraction(self) -> float:
        total = (self.end - self.start).days
        if total <= 0:
            return 1.0
        elapsed = (min(max(self.as_of, self.start), self.end) - self.start).days
        return round(elapsed / total, 4)


@dataclass(frozen=True, slots=True)
class RoleStratum:
    role: HolderRole
    composition: tuple[tuple[FulfillmentVerdict, int], ...]
    scored_pledges: int
    closed_pledges: int
    open_pledges: int
    kept_equivalent: float
    rate: float | None
    credible_interval: tuple[float, float] | None
    rate_withheld_reason: str | None
    topics: tuple[tuple[str, int], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Scorecard:
    methodology_version: str
    tracked_pledges: int
    excluded_vague_pledges: int
    strata: tuple[RoleStratum, ...]
    credible_level: float
    min_closed_for_rate: int
    mandate_progress: MandateProgress | None = None

    def stratum(self, role: HolderRole) -> RoleStratum | None:
        return next((item for item in self.strata if item.role is role), None)


def _rate_and_interval(
    kept: int,
    partial: int,
    broken: int,
    methodology: ScoringMethodology,
) -> tuple[float, float | None, tuple[float, float] | None, str | None]:
    closed = kept + partial + broken
    kept_equivalent = kept + methodology.partial_weight * partial
    if closed == 0:
        return kept_equivalent, None, None, "no_closed_pledges"
    failures = broken + (1.0 - methodology.partial_weight) * partial
    interval = beta_equal_tailed_interval(
        kept_equivalent + methodology.prior_alpha,
        failures + methodology.prior_beta,
        methodology.credible_level,
    )
    interval = (round(interval[0], 4), round(interval[1], 4))
    if closed < methodology.min_closed_for_rate:
        return kept_equivalent, None, interval, "below_minimum_closed_pledges"
    return kept_equivalent, round(kept_equivalent / closed, 4), interval, None


def compute_scorecard(
    outcomes: Iterable[PledgeOutcome],
    *,
    methodology: ScoringMethodology = DEFAULT_METHODOLOGY,
    mandate_progress: MandateProgress | None = None,
) -> Scorecard:
    items = list(outcomes)
    seen: set[int] = set()
    for item in items:
        if item.pledge_id in seen:
            raise ValueError(f"pledge {item.pledge_id} appears twice")
        seen.add(item.pledge_id)

    scored = [item for item in items if item.specificity is not PledgeSpecificity.VAGUE]
    by_role: dict[HolderRole, list[PledgeOutcome]] = {}
    for item in scored:
        by_role.setdefault(item.role, []).append(item)

    strata: list[RoleStratum] = []
    for role in HolderRole:
        members = by_role.get(role)
        if not members:
            continue
        counts = Counter(item.verdict for item in members)
        kept = counts[FulfillmentVerdict.KEPT]
        partial = counts[FulfillmentVerdict.PARTIALLY_KEPT]
        broken = counts[FulfillmentVerdict.BROKEN]
        closed = kept + partial + broken
        kept_equivalent, rate, interval, reason = _rate_and_interval(
            kept, partial, broken, methodology
        )
        topics = Counter(item.topic_code for item in members if item.topic_code)
        strata.append(
            RoleStratum(
                role=role,
                composition=tuple(
                    (verdict, counts[verdict]) for verdict in COMPOSITION_ORDER
                ),
                scored_pledges=len(members),
                closed_pledges=closed,
                open_pledges=sum(
                    1 for item in members if item.verdict not in CLOSED_VERDICTS
                ),
                kept_equivalent=kept_equivalent,
                rate=rate,
                credible_interval=interval,
                rate_withheld_reason=reason,
                topics=tuple(sorted(topics.items(), key=lambda pair: (-pair[1], pair[0]))),
            )
        )

    return Scorecard(
        methodology_version=methodology.version,
        tracked_pledges=len(items),
        excluded_vague_pledges=len(items) - len(scored),
        strata=tuple(strata),
        credible_level=methodology.credible_level,
        min_closed_for_rate=methodology.min_closed_for_rate,
        mandate_progress=mandate_progress,
    )
