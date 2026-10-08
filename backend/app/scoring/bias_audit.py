"""Periodic partisan-skew audit of closed verdicts.

The question is not "do parties score differently" (they legitimately can) but
"do parties score differently *at equal role and period*". Within each
(role, period) stratum every political bloc is compared with all other blocs;
the strata are then pooled with Cochran-Mantel-Haenszel-style weights
``n1 * n0 / (n1 + n0)``.

A flag is a prompt for a methodological review of the underlying verdicts, not
evidence of bias by itself.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

_Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class BiasObservation:
    bloc: str
    role: str
    period: str
    value: float  # closed verdict value in [0, 1]


@dataclass(frozen=True, slots=True)
class BlocComparison:
    bloc: str
    stratum_count: int
    bloc_pledges: int
    other_pledges: int
    weighted_difference: float | None
    confidence_interval: tuple[float, float] | None
    flagged: bool


@dataclass(frozen=True, slots=True)
class BiasAuditReport:
    min_per_group: int
    flag_threshold: float
    comparisons: tuple[BlocComparison, ...]
    skipped_strata: int

    @property
    def flagged(self) -> tuple[BlocComparison, ...]:
        return tuple(item for item in self.comparisons if item.flagged)


def _mean_and_variance(values: list[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    return mean, sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def partisan_skew_audit(
    observations: Iterable[BiasObservation],
    *,
    min_per_group: int = 5,
    flag_threshold: float = 0.15,
) -> BiasAuditReport:
    strata: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in observations:
        if not 0.0 <= item.value <= 1.0:
            raise ValueError("verdict values must be within [0, 1]")
        strata[(item.role, item.period)][item.bloc].append(item.value)

    # bloc -> list of (weight, difference, variance, n_bloc, n_other)
    contributions: dict[str, list[tuple[float, float, float, int, int]]] = defaultdict(list)
    skipped = 0
    for blocs in strata.values():
        eligible = {bloc: values for bloc, values in blocs.items() if len(values) >= min_per_group}
        if len(eligible) < 2:
            skipped += 1
            continue
        for bloc, values in eligible.items():
            others = [value for other, vs in eligible.items() if other != bloc for value in vs]
            mean_bloc, var_bloc = _mean_and_variance(values)
            mean_other, var_other = _mean_and_variance(others)
            n1, n0 = len(values), len(others)
            weight = n1 * n0 / (n1 + n0)
            variance = var_bloc / n1 + var_other / n0
            contributions[bloc].append((weight, mean_bloc - mean_other, variance, n1, n0))

    comparisons = []
    for bloc in sorted(contributions):
        parts = contributions[bloc]
        total_weight = sum(weight for weight, *_ in parts)
        difference = sum(weight * diff for weight, diff, *_ in parts) / total_weight
        variance = sum((weight / total_weight) ** 2 * var for weight, _d, var, *_ in parts)
        half_width = _Z_95 * math.sqrt(variance)
        interval = (round(difference - half_width, 4), round(difference + half_width, 4))
        excludes_zero = interval[0] > 0 or interval[1] < 0
        comparisons.append(
            BlocComparison(
                bloc=bloc,
                stratum_count=len(parts),
                bloc_pledges=sum(part[3] for part in parts),
                other_pledges=sum(part[4] for part in parts),
                weighted_difference=round(difference, 4),
                confidence_interval=interval,
                flagged=excludes_zero and abs(difference) >= flag_threshold,
            )
        )
    return BiasAuditReport(
        min_per_group=min_per_group,
        flag_threshold=flag_threshold,
        comparisons=tuple(comparisons),
        skipped_strata=skipped,
    )
