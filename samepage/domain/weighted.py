"""Weighted rubric totals computed as exact fractions (`fractions.Fraction`).

Invariant: Σ w·v / Σ w is a `fractions.Fraction`, never a float, until it is
rendered. Standard library only.

Why: two reviews with the same total compare equal, so a tie is a real tie and the
documented tie-break (JUDGING.md) decides the order, not rounding.

Rejected alternative: `float`, where the same total reached in a different order can
differ in the last bit (0.1 + 0.2 != 0.3) and silently break a tie.
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
