"""Rank intervals from draws of â, conditional on λ. Uncertainty in λ is ignored."""

from __future__ import annotations

import numpy as np


def rank_draws(beta: np.ndarray, cov: np.ndarray, *, n_draws: int, seed: int) -> dict:
    jitter = np.eye(len(beta)) * 1e-12
    matrix = 0.5 * (cov + cov.T) + jitter
    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(beta, matrix, size=n_draws, check_valid="ignore")
    order = np.argsort(-draws, axis=1, kind="mergesort")
    ranks = np.empty_like(order)
    rows = np.arange(n_draws)[:, None]
    ranks[rows, order] = np.arange(1, beta.shape[0] + 1)
    lo = np.percentile(ranks, 5, axis=0)
    hi = np.percentile(ranks, 95, axis=0)
    p_top5 = (ranks <= 5).mean(axis=0)
    return {
        "rank_lo": [int(round(v)) for v in lo],
        "rank_hi": [int(round(v)) for v in hi],
        "p_top5": [float(v) for v in p_top5],
    }


def tie_banner(p_top5: list[float], floor: float = 0.10) -> dict:
    """Lowest rank whose project still has P(top-5) ≥ floor. Ranks are 1-based positions in the supplied list order? 

    Callers pass p_top5 aligned with rank order (index 0 is rank 1).
    """
    m = 0
    for index, probability in enumerate(p_top5, start=1):
        if probability >= floor:
            m = index
    return {
        "m": m,
        "text": f"statistical tie for the top 5 across ranks 1–{m}" if m else "no project has P(top-5) ≥ 0.10",
    }
