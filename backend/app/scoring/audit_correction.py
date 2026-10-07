"""Blind-audit sampling and design-based correction of aggregate rates.

Egami et al. (2023, "Using imperfect surrogates for downstream inference",
design-based supervised learning) show that aggregates computed from imperfect
labels (LLM-assisted or single-coder) are biased, and that a random subsample
re-coded by humans with *known* inclusion probabilities restores valid
inference. For a mean the estimator is:

    Y~_i = Yhat_i + (R_i / pi_i) * (Y_i - Yhat_i)
    estimate = mean(Y~),  se = sd(Y~) / sqrt(N)

where ``Yhat`` is the published verdict value, ``Y`` the blind audit value, ``R``
the sampling indicator and ``pi`` the inclusion probability. The correction is
unbiased whatever the quality of ``Yhat``; better first-pass labels only make
the interval narrower.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_Z_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class AuditSample:
    sample_key: str
    seed: int
    population_size: int
    selected_ids: tuple[int, ...]

    @property
    def inclusion_probability(self) -> float:
        if self.population_size == 0:
            return 0.0
        return len(self.selected_ids) / self.population_size


def draw_audit_sample(
    population_ids: Sequence[int], *, size: int, seed: int, sample_key: str
) -> AuditSample:
    """Simple random sample without replacement, reproducible from the seed."""

    if size < 0:
        raise ValueError("sample size must be non-negative")
    population = sorted(set(population_ids))
    size = min(size, len(population))
    selected = sorted(random.Random(seed).sample(population, size))
    return AuditSample(
        sample_key=sample_key,
        seed=seed,
        population_size=len(population),
        selected_ids=tuple(selected),
    )


@dataclass(frozen=True, slots=True)
class CorrectedEstimate:
    naive_estimate: float | None
    corrected_estimate: float | None
    standard_error: float | None
    confidence_interval: tuple[float, float] | None
    population_size: int
    audited: int
    disagreement_rate: float | None


def design_based_mean(
    predictions: Mapping[int, float],
    audited: Mapping[int, float],
    *,
    inclusion_probability: float | Mapping[int, float],
) -> CorrectedEstimate:
    """Design-based corrected mean of ``predictions`` using ``audited`` labels.

    ``audited`` keys must be a subset of ``predictions`` keys and must have been
    selected with the stated inclusion probability (uniform or per item).
    """

    population = len(predictions)
    unknown = set(audited) - set(predictions)
    if unknown:
        raise ValueError(f"audited ids outside the population: {sorted(unknown)}")
    if population == 0:
        return CorrectedEstimate(None, None, None, None, 0, 0, None)

    def pi(item_id: int) -> float:
        value = (
            inclusion_probability.get(item_id, 0.0)
            if isinstance(inclusion_probability, Mapping)
            else inclusion_probability
        )
        if not 0.0 < value <= 1.0:
            raise ValueError("inclusion probability of audited items must be in (0, 1]")
        return value

    pseudo = []
    for item_id, predicted in predictions.items():
        if item_id in audited:
            pseudo.append(predicted + (audited[item_id] - predicted) / pi(item_id))
        else:
            pseudo.append(predicted)
    naive = sum(predictions.values()) / population
    estimate = sum(pseudo) / population
    if population > 1:
        variance = sum((value - estimate) ** 2 for value in pseudo) / (population - 1)
        se = math.sqrt(variance / population)
    else:
        se = 0.0
    disagreements = sum(
        1 for item_id, value in audited.items() if not math.isclose(value, predictions[item_id])
    )
    return CorrectedEstimate(
        naive_estimate=round(naive, 4),
        corrected_estimate=round(estimate, 4),
        standard_error=round(se, 4),
        confidence_interval=(
            round(estimate - _Z_95 * se, 4),
            round(estimate + _Z_95 * se, 4),
        ),
        population_size=population,
        audited=len(audited),
        disagreement_rate=(
            round(disagreements / len(audited), 4) if audited else None
        ),
    )
