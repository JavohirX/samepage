"""Raptors k=10 shrinkage, beside the data-driven k from a one-way ICC."""

from __future__ import annotations

import numpy as np


def raptors_k(raw_mean: float, n: int, grand: float, k: float = 10.0) -> float:
    return (n * raw_mean + k * grand) / (n + k)


def anova_k(y: np.ndarray, project_ids: list[str]) -> dict:
    """ICC of a single review and k = σ²_within / σ²_between. None when the between component is not positive."""
    labels = list(dict.fromkeys(project_ids))
    index = {key: i for i, key in enumerate(labels)}
    group = np.array([index[key] for key in project_ids])
    n_groups = len(labels)
    n_obs = len(y)
    if n_groups < 2 or n_obs <= n_groups:
        return {"icc": None, "k_data": None, "reliability_n3": None}
    grand = float(y.mean())
    ssb = 0.0
    ssw = 0.0
    sizes = []
    for i in range(n_groups):
        chunk = y[group == i]
        sizes.append(len(chunk))
        ssb += len(chunk) * (float(chunk.mean()) - grand) ** 2
        ssw += float(np.sum((chunk - float(chunk.mean())) ** 2))
    msb = ssb / (n_groups - 1)
    msw = ssw / (n_obs - n_groups)
    n0 = (n_obs - sum(n * n for n in sizes) / n_obs) / (n_groups - 1)
    if msb <= msw or n0 <= 0 or msw <= 0:
        return {"icc": 0.0, "k_data": None, "reliability_n3": 0.0}
    sigma_p = (msb - msw) / n0
    icc = sigma_p / (sigma_p + msw)
    return {
        "icc": float(icc),
        "k_data": float(msw / sigma_p),
        "reliability_n3": float((3 * icc) / (1 + 2 * icc)),
    }
