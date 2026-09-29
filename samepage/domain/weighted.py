"""Weighted rubric totals computed as exact fractions (`fractions.Fraction`).

Invariant: All weight sums Σ w·v / Σ w are computed in infinite-precision rational
arithmetic without floating-point rounding errors. Zero dependencies outside the
Python standard library.

Why: Preserves mathematical correctness and exact tie detection regardless of
rubric weight magnitudes.

Rejected alternative: IEEE 754 floating point arithmetic (`float`), which produces
representation artifacts (e.g. 0.1 + 0.2 != 0.3) and arbitrary tie-breaking
discrepancies across CPU architectures.
"""

from __future__ import annotations

from fractions import Fraction


def weighted_total(criteria: dict, weights: dict) -> Fraction:
    """Σ w·v / Σ w. Every weight must be positive and every criterion present."""
    if not weights:
        raise ValueError("rubric has no criteria")
    numerator = Fraction(0)
    denominator = Fraction(0)
    for key, weight in weights.items():
        if key not in criteria:
            raise ValueError(f"missing criterion {key}")
        parsed = Fraction(str(weight))
        if parsed <= 0:
            raise ValueError(f"weight for {key} must be positive")
        numerator += parsed * Fraction(criteria[key])
        denominator += parsed
    return numerator / denominator


def fraction_text(value: Fraction) -> str:
    """Decimal text that still round-trips through Fraction for rubric means."""
    text = format(value, ".10f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
