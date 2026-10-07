"""Inter-coder agreement: Krippendorff's alpha.

The pledge literature reports reliability as Krippendorff's alpha, which handles
any number of coders, missing codes and nominal or ordinal categories. Two
editors who do not agree with each other set the ceiling for the model, so this
is measured on the gold set and on the blind audit sample.

Implementation follows Krippendorff (2011), "Computing Krippendorff's
Alpha-Reliability", via the coincidence matrix.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


class AlphaMetric(StrEnum):
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    INTERVAL = "interval"


@dataclass(frozen=True, slots=True)
class AlphaResult:
    alpha: float | None
    metric: AlphaMetric
    pairable_units: int
    pairable_values: int
    observed_disagreement: float | None
    expected_disagreement: float | None


def _coincidences(units: Sequence[Sequence[T | None]]) -> tuple[Counter, int]:
    matrix: Counter = Counter()
    pairable_units = 0
    for unit in units:
        values = [value for value in unit if value is not None]
        m = len(values)
        if m < 2:
            continue
        pairable_units += 1
        for i, first in enumerate(values):
            for j, second in enumerate(values):
                if i != j:
                    matrix[(first, second)] += 1.0 / (m - 1)
    return matrix, pairable_units


def krippendorff_alpha(
    units: Sequence[Sequence[T | None]],
    *,
    metric: AlphaMetric = AlphaMetric.NOMINAL,
    order: Sequence[T] | None = None,
) -> AlphaResult:
    """Alpha for ``units``: one row per coded item, one entry per coder.

    ``None`` marks a missing code. ``order`` is required for the ordinal metric;
    the interval metric requires numeric values.
    """

    matrix, pairable_units = _coincidences(units)
    marginals: Counter = Counter()
    for (first, _second), weight in matrix.items():
        marginals[first] += weight
    n = sum(marginals.values())
    total_values = round(n)
    if n <= 1 or len(marginals) == 0:
        return AlphaResult(None, metric, pairable_units, total_values, None, None)

    categories = list(marginals)
    if metric is AlphaMetric.ORDINAL:
        if order is None:
            raise ValueError("ordinal alpha requires an explicit category order")
        missing = [value for value in categories if value not in order]
        if missing:
            raise ValueError(f"values not in order: {missing!r}")
        rank = {value: index for index, value in enumerate(order)}
        ordered = sorted(categories, key=rank.__getitem__)
        position = {value: index for index, value in enumerate(ordered)}

        def delta(c: T, k: T) -> float:
            low, high = sorted((position[c], position[k]))
            span = sum(marginals[ordered[g]] for g in range(low, high + 1))
            return (span - (marginals[c] + marginals[k]) / 2.0) ** 2

    elif metric is AlphaMetric.INTERVAL:

        def delta(c: T, k: T) -> float:
            return (float(c) - float(k)) ** 2  # type: ignore[arg-type]

    else:

        def delta(c: T, k: T) -> float:
            return 0.0 if c == k else 1.0

    observed = sum(weight * delta(c, k) for (c, k), weight in matrix.items()) / n
    expected = sum(
        marginals[c] * marginals[k] * delta(c, k)
        for c in categories
        for k in categories
    ) / (n * (n - 1))
    if expected == 0:
        alpha = 1.0 if observed == 0 else None
    else:
        alpha = 1.0 - observed / expected
    return AlphaResult(
        alpha=None if alpha is None else round(alpha, 4),
        metric=metric,
        pairable_units=pairable_units,
        pairable_values=total_values,
        observed_disagreement=round(observed, 6),
        expected_disagreement=round(expected, 6),
    )
