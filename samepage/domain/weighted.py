"""Weighted rubric totals as exact fractions."""

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
