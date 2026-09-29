"""Feedback pack generation and distributional analysis (S9).

Pure domain logic: per-criterion means, percentile calculation, and text histogram.
Free of Django and web layers.
"""

from __future__ import annotations

import math
from typing import Any


def calculate_percentile(all_scores: list[float], team_score: float) -> float:
    """Calculate percentile rank of team_score within all_scores (0 to 100)."""
    if not all_scores:
        return 100.0
    below = sum(1 for s in all_scores if s < team_score)
    equal = sum(1 for s in all_scores if abs(s - team_score) < 1e-6)
    percentile = (below + 0.5 * equal) / len(all_scores) * 100.0
    return round(percentile, 1)


def generate_text_histogram(
    all_scores: list[float],
    team_score: float | None = None,
    num_bins: int = 5,
    min_val: float = 0.0,
    max_val: float = 100.0,
    bar_char: str = "█",
    max_bar_width: int = 20,
) -> str:
    """Generate a clean ASCII/Unicode text histogram with team score indicator."""
    if not all_scores:
        return "No score distribution available."

    actual_min = min(min_val, min(all_scores))
    actual_max = max(max_val, max(all_scores))
    if actual_max <= actual_min:
        actual_max = actual_min + 1.0

    bin_width = (actual_max - actual_min) / num_bins
    counts = [0] * num_bins
    team_bin_idx = -1

    for s in all_scores:
        idx = int((s - actual_min) / bin_width)
        if idx >= num_bins:
            idx = num_bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1

    if team_score is not None:
        team_bin_idx = int((team_score - actual_min) / bin_width)
        if team_bin_idx >= num_bins:
            team_bin_idx = num_bins - 1
        if team_bin_idx < 0:
            team_bin_idx = 0

    max_count = max(counts) if counts else 1
    total = len(all_scores)

    lines = []
    for i in range(num_bins):
        low = actual_min + i * bin_width
        high = actual_min + (i + 1) * bin_width
        cnt = counts[i]
        pct = (cnt / total) * 100.0 if total > 0 else 0.0
        bar_len = int((cnt / max_count) * max_bar_width) if max_count > 0 else 0
        bar = bar_char * bar_len
        marker = " ◄ YOUR SCORE" if i == team_bin_idx else ""
        lines.append(f"[{low:5.1f} - {high:5.1f}): {cnt:3d} ({pct:4.1f}%) | {bar:<{max_bar_width}}{marker}")

    return "\n".join(lines)


def build_feedback_pack(
    project_id: str,
    project_title: str,
    overall_score: float,
    all_project_scores: list[float],
    criteria_means: dict[str, float],
    anonymous_comments: list[str],
) -> dict[str, Any]:
    """Assemble complete feedback pack dictionary."""
    percentile = calculate_percentile(all_project_scores, overall_score)
    histogram = generate_text_histogram(all_project_scores, overall_score)

    return {
        "project_id": project_id,
        "title": project_title,
        "overall_score": round(overall_score, 2),
        "percentile": percentile,
        "histogram": histogram,
        "criteria_means": criteria_means,
        "comments": anonymous_comments,
    }
