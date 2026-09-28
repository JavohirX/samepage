"""Profile REML for y = X a + Z b + e, with one random intercept per judge.

λ = σ²/τ². The grid is part of the method: t = ln λ, stage 1 steps 0.05 from
ln 0.1 across 185 points, stage 2 steps 0.001 across ±0.05 around the stage-1
maximiser (286 evaluations). Ties keep the earlier point.
"""

from __future__ import annotations

import math

import numpy as np

LN_LO = math.log(0.1)
STAGE1_STEP = 0.05
STAGE1_COUNT = 185  # k = 0..184
STAGE2_STEP = 0.001
STAGE2_RADIUS = 50  # m = -50..50


def design(project_ids: list[str], judge_ids: list[str], y: np.ndarray):
    projects = sorted(set(project_ids))
    judges = sorted(set(judge_ids))
    p_index = {key: i for i, key in enumerate(projects)}
    j_index = {key: i for i, key in enumerate(judges)}
    n_obs = len(y)
    x = np.zeros((n_obs, len(projects)))
    z = np.zeros((n_obs, len(judges)))
    for i, (project, judge) in enumerate(zip(project_ids, judge_ids)):
        x[i, p_index[project]] = 1.0
        z[i, j_index[judge]] = 1.0
    return projects, judges, x, z


def profile_loglik(x: np.ndarray, z: np.ndarray, y: np.ndarray, lam: float):
    """Return (ℓ, σ², â, cov_factor) where cov(â) = σ² · cov_factor."""
    if not math.isfinite(lam) or lam <= 0:
        return -math.inf, None, None, None
    g = 1.0 / lam
    n_obs, n_projects = x.shape
    n_judge = np.sum(z, axis=0)
    logdet_h = float(np.sum(np.log1p(g * n_judge)))
    weight = 1.0 / ((1.0 / g) + n_judge)

    def hinv(mat: np.ndarray) -> np.ndarray:
        zt = z.T @ mat
        if zt.ndim == 1:
            corr = z @ (weight * zt)
        else:
            corr = z @ (weight[:, None] * zt)
        return mat - corr

    hi_x = hinv(x)
    xt_hi_x = x.T @ hi_x
    sign, logdet_x = np.linalg.slogdet(xt_hi_x)
    if sign <= 0:
        return -math.inf, None, None, None
    beta = np.linalg.solve(xt_hi_x, x.T @ hinv(y))
    resid = y - x @ beta
    quad = float(resid @ hinv(resid))
    df = n_obs - n_projects
    if df <= 0 or quad <= 0:
        return -math.inf, None, None, None
    sigma2 = quad / df
    llf = -0.5 * (df * math.log(sigma2) + logdet_h + float(logdet_x))
    cov_factor = np.linalg.inv(xt_hi_x)
    return llf, sigma2, beta, cov_factor


def dense_effects(x: np.ndarray, z: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Same GLS estimator with an explicit inverse of V. For the differential test."""
    g = 1.0 / lam
    eye = np.eye(x.shape[0])
    v = eye + g * (z @ z.T)
    vi = np.linalg.inv(v)
    gram = x.T @ vi @ x
    return np.linalg.solve(gram, x.T @ vi @ y)


def stage1_grid() -> list[tuple[float, float]]:
    """(t, λ) for k = 0..184."""
    return [(LN_LO + STAGE1_STEP * k, math.exp(LN_LO + STAGE1_STEP * k)) for k in range(STAGE1_COUNT)]


def stage2_grid(t1: float) -> list[tuple[float, float]]:
    return [
        (t1 + STAGE2_STEP * m, math.exp(t1 + STAGE2_STEP * m))
        for m in range(-STAGE2_RADIUS, STAGE2_RADIUS + 1)
    ]


def choose_lambda(x: np.ndarray, z: np.ndarray, y: np.ndarray):
    """First maximiser on the two-stage grid. Returns a dict."""
    best_ll = -math.inf
    best_t = None
    best_lam = None
    evaluations = 0
    for t, lam in stage1_grid():
        llf, _, _, _ = profile_loglik(x, z, y, lam)
        evaluations += 1
        if llf > best_ll:
            best_ll = llf
            best_t = t
            best_lam = lam
    if best_t is None:
        raise RuntimeError("REML grid has no finite likelihood")
    stage1_t = best_t
    stage1_k = int(round((stage1_t - LN_LO) / STAGE1_STEP))
    for t, lam in stage2_grid(stage1_t):
        llf, _sigma2, _beta, _cov_factor = profile_loglik(x, z, y, lam)
        evaluations += 1
        if llf > best_ll:
            best_ll = llf
            best_t = t
            best_lam = lam
    # Recompute the winning point so the returned effects match the chosen λ,
    # including the case where stage 1 already held the maximum.
    sigma2, beta, cov_factor = profile_loglik(x, z, y, best_lam)[1:]
    at_edge = stage1_k in (0, STAGE1_COUNT - 1)
    return {
        "lambda": float(best_lam),
        "t": float(best_t),
        "loglik": float(best_ll),
        "sigma2": float(sigma2),
        "beta": beta,
        "cov_factor": cov_factor,
        "evaluations": evaluations,
        "at_bound": at_edge,
        "stage1_t": float(stage1_t),
    }
