"""Beta distribution helpers implemented with the standard library only.

Used for the beta-binomial credible interval of the fulfilment rate. Small
counts are the normal case for local politicians, so the interval matters more
than the point estimate.
"""

from __future__ import annotations

import math

_EPSILON = 3.0e-14
_TINY = 1.0e-300
_MAX_ITERATIONS = 300


def _continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz evaluation of the incomplete-beta continued fraction."""

    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + aa / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPSILON:
            break
    return h


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """I_x(a, b), the CDF of Beta(a, b) at ``x``."""

    if a <= 0 or b <= 0:
        raise ValueError("beta parameters must be positive")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _continued_fraction(a, b, x) / a
    return 1.0 - front * _continued_fraction(b, a, 1.0 - x) / b


def beta_quantile(probability: float, a: float, b: float) -> float:
    """Inverse CDF of Beta(a, b) by bisection (monotone, robust, deterministic)."""

    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be within [0, 1]")
    if probability == 0.0:
        return 0.0
    if probability == 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(200):
        middle = (low + high) / 2.0
        if regularized_incomplete_beta(middle, a, b) < probability:
            low = middle
        else:
            high = middle
        if high - low < 1e-12:
            break
    return (low + high) / 2.0


def beta_equal_tailed_interval(
    a: float, b: float, level: float
) -> tuple[float, float]:
    if not 0.0 < level < 1.0:
        raise ValueError("credible level must be within (0, 1)")
    tail = (1.0 - level) / 2.0
    return beta_quantile(tail, a, b), beta_quantile(1.0 - tail, a, b)
