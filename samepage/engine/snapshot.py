"""One snapshot: raw, z, REML, k=10, intervals, sensitivity, leave-one-judge-out, flags."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from samepage.domain.canonical import ranking_sha256
from samepage.domain.weighted import fraction_text, weighted_total
from samepage.engine.reml import choose_lambda, dense_effects, design, profile_loglik
from samepage.engine.shrink import anova_k, raptors_k
from samepage.engine.uncertainty import rank_draws, tie_banner
from samepage.engine.zscore import judge_z, project_z_means

DRAW_SEED = 20260301
N_DRAWS = 4000
SENSITIVITY = (5.0, 10.0, 20.0, 30.0, 50.0)


class NotIdentifiable(ValueError):
    """The judge-bias model has nothing to fit: within every project, all counted reviews agree."""


def kendall_tau_b(left: dict[str, int], right: dict[str, int]) -> float | None:
    keys = [key for key in left if key in right]
    n = len(keys)
    if n < 2:
        return None
    conc = disc = ties_l = ties_r = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = left[keys[i]] - left[keys[j]]
            b = right[keys[i]] - right[keys[j]]
            if a == 0 and b == 0:
                continue
            if a == 0:
                ties_l += 1
            elif b == 0:
                ties_r += 1
            elif a * b > 0:
                conc += 1
            else:
                disc += 1
    denom_l = conc + disc + ties_l
    denom_r = conc + disc + ties_r
    if denom_l == 0 or denom_r == 0:
        return None
    return (conc - disc) / math.sqrt(denom_l * denom_r)


def _rank_map(rows: list[dict], score_key: str) -> dict[str, int]:
    ordered = sorted(
        rows,
        key=lambda row: (
            -(row[score_key] if row[score_key] is not None else -1e18),
            row["submitted_at"],
            row["id"],
        ),
    )
    return {row["id"]: index for index, row in enumerate(ordered, start=1)}


def _total(review: dict, weights: dict):
    """A review's weighted rubric total. A review may carry its track's weights; else the event's."""
    return weighted_total(review["criteria"], review.get("weights") or weights)


def _fit_arrays(reviews: list[dict], weights: dict):
    project_ids = []
    judge_ids = []
    values = []
    for review in reviews:
        total = _total(review, weights)
        project_ids.append(review["project_id"])
        judge_ids.append(review["judge_id"])
        values.append(float(total))
    y = np.array(values, dtype=float)
    projects, judges, x, z = design(project_ids, judge_ids, y)
    return project_ids, judge_ids, y, projects, judges, x, z


def _effects_at(x, z, y, lam: float):
    _llf, sigma2, beta, cov_factor = profile_loglik(x, z, y, lam)
    return beta, sigma2, cov_factor, _llf


def build_snapshot(
    reviews: list[dict],
    projects_meta: dict[str, dict],
    weights: dict,
    *,
    seed: int = DRAW_SEED,
    n_draws: int = N_DRAWS,
    with_lojo: bool = True,
    with_draws: bool = True,
    judges_present: list[str] | None = None,
) -> dict:
    """reviews are the counted rows only. projects_meta covers the projects being ranked."""
    if not reviews:
        return {"method": "raw_fallback", "reason": "no counted reviews", "rows": [], "ranking_sha256": ""}
    # Checked on exact fractions. With no difference between any project's reviews, the residual after
    # the project means is zero and the REML likelihood is undefined; in floating point it is rounding
    # noise instead, which would pick a λ from noise. The caller falls back to raw weighted means.
    exact_totals: dict[str, set] = defaultdict(set)
    for review in reviews:
        exact_totals[review["project_id"]].add(_total(review, weights))
    if all(len(values) == 1 for values in exact_totals.values()):
        raise NotIdentifiable(
            "within each project every counted review gives the same weighted total, "
            "so no variation is left to measure a judge's lean from"
        )

    project_ids, judge_ids, y, projects, judges, x, z = _fit_arrays(reviews, weights)
    chosen = choose_lambda(x, z, y)
    beta = chosen["beta"]
    sigma2 = chosen["sigma2"]
    cov = sigma2 * chosen["cov_factor"]
    effect = {project: float(beta[i]) for i, project in enumerate(projects)}

    by_project: dict[str, list[float]] = defaultdict(list)
    submitted = {}
    for review, value in zip(reviews, y):
        by_project[review["project_id"]].append(float(value))
        submitted[review["project_id"]] = projects_meta.get(review["project_id"], {}).get(
            "submitted_at", ""
        )
    raw = {project: float(np.mean(vals)) for project, vals in by_project.items()}
    n_reviews = {project: len(vals) for project, vals in by_project.items()}
    grand = float(y.mean())
    k10 = {project: raptors_k(raw[project], n_reviews[project], grand) for project in projects}

    z_values, z_rows = judge_z(judge_ids, y)
    z_means = project_z_means(project_ids, z_values, projects)

    intervals = {"rank_lo": [None] * len(projects), "rank_hi": [None] * len(projects), "p_top5": [None] * len(projects)}
    if with_draws:
        intervals = rank_draws(beta, cov, n_draws=n_draws, seed=seed)

    p_of = {project: intervals["p_top5"][i] for i, project in enumerate(projects)}
    base_rows = []
    for i, project in enumerate(projects):
        meta = projects_meta.get(project, {})
        base_rows.append(
            {
                "id": project,
                "title": meta.get("title", ""),
                "track": meta.get("track", ""),
                "submitted_at": meta.get("submitted_at", submitted.get(project, "")),
                "adjusted": effect[project],
                "raw_mean": raw[project],
                "raw_mean_exact": fraction_text(
                    sum(
                        (
                            _total(review, weights)
                            for review in reviews
                            if review["project_id"] == project
                        ),
                        start=0,
                    )
                    / n_reviews[project]
                ),
                "raptors_k10": k10[project],
                "z_mean": z_means[project],
                "n_reviews": n_reviews[project],
                "p_top5": p_of[project],
                "rank_lo": intervals["rank_lo"][i],
                "rank_hi": intervals["rank_hi"][i],
            }
        )

    def sort_key(row, score):
        p_top = row["p_top5"] if row["p_top5"] is not None else -1.0
        return (-(score if score is not None else -1e18), -p_top, -row["n_reviews"], row["submitted_at"], row["id"])

    ordered = sorted(base_rows, key=lambda row: sort_key(row, row["adjusted"]))
    for index, row in enumerate(ordered, start=1):
        row["rank"] = index
    raw_ranks = _rank_map(base_rows, "raw_mean")
    z_rows_rankable = [row for row in base_rows if row["z_mean"] is not None]
    z_ranks = _rank_map(
        [{**row, "z_mean": row["z_mean"]} for row in z_rows_rankable],
        "z_mean",
    )
    k_ranks = _rank_map(base_rows, "raptors_k10")
    for row in ordered:
        row["raw_rank"] = raw_ranks[row["id"]]
        row["z_rank"] = z_ranks.get(row["id"])
        row["k10_rank"] = k_ranks[row["id"]]
        row["rank_move_raw"] = row["raw_rank"] - row["rank"]
        row["adjusted_display"] = f"{row['adjusted']:.3f}"
        row["raw_display"] = f"{row['raw_mean']:.3f}"
        row["k10_display"] = f"{row['raptors_k10']:.3f}"
        row["p_top5_display"] = "" if row["p_top5"] is None else f"{row['p_top5']:.3f}"

    # Tie groups: identical adjusted to 1e-9.
    tie_group = {}
    group_index = 0
    previous = None
    for row in ordered:
        if previous is None or abs(row["adjusted"] - previous) > 1e-9:
            group_index += 1
            previous = row["adjusted"]
        tie_group[row["id"]] = group_index
        row["tie_group"] = group_index

    track_best: dict[str, list] = defaultdict(list)
    for row in ordered:
        track_best[row["track"]].append(row)
    for row in ordered:
        mates = track_best[row["track"]]
        row["track_rank"] = 1 + next(i for i, mate in enumerate(mates) if mate["id"] == row["id"])

    sha = ranking_sha256([(row["id"], row["rank"]) for row in ordered])
    top5 = [row["id"] for row in ordered[:5]]
    p_in_rank_order = [row["p_top5"] or 0.0 for row in ordered]
    banner = tie_banner(p_in_rank_order) if with_draws else {"m": None, "text": "intervals not computed"}

    ablation = _ablation(ordered, raw_ranks, z_ranks, k_ranks)
    sensitivity = _sensitivity(x, z, y, projects, ordered, chosen["lambda"])
    lojo = _lojo(reviews, weights, projects, top5) if with_lojo else []
    anova = anova_k(y, project_ids)
    present = set(judges_present or judges)
    flags = _flags(reviews, projects_meta, z_rows, present, n_reviews)
    leans = judge_leans(judge_ids, y, y - x @ beta, chosen["lambda"], present, flags)

    return {
        "method": "reml",
        "lambda": chosen["lambda"],
        "loglik": chosen["loglik"],
        "sigma2": chosen["sigma2"],
        "at_bound": chosen["at_bound"],
        "evaluations": chosen["evaluations"],
        "grand_mean": grand,
        "k_data": anova.get("k_data"),
        "icc": anova.get("icc"),
        "reliability_n3": anova.get("reliability_n3"),
        "n_reviews": int(len(reviews)),
        "n_projects": len(projects),
        "n_judges": len(judges),
        "rows": ordered,
        "ranking_sha256": sha,
        "top5": top5,
        "banner": banner,
        "ablation": ablation,
        "z_failures": [row for row in z_rows if row["status"] != "ok"],
        "z_judges": z_rows,
        "sensitivity": sensitivity,
        "lojo": lojo,
        "flags": flags,
        "judge_leans": leans,
        "kendall_raw": kendall_tau_b({row["id"]: row["rank"] for row in ordered}, raw_ranks),
        "seed": seed,
        "input_sha256": _input_sha(reviews),
        "dense_max_abs": _dense_gap(x, z, y, chosen["lambda"], beta),
    }


def _dense_gap(x, z, y, lam, beta) -> float:
    try:
        other = dense_effects(x, z, y, lam)
    except np.linalg.LinAlgError:
        return float("nan")
    return float(np.max(np.abs(other - beta)))


def _input_sha(reviews: list[dict]) -> str:
    import hashlib

    parts = []
    for review in sorted(reviews, key=lambda row: (row["judge_id"], row["project_id"])):
        crit = ",".join(f"{key}:{review['criteria'][key]}" for key in sorted(review["criteria"]))
        parts.append(f"{review['judge_id']}|{review['project_id']}|{crit}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _ablation(ordered, raw_ranks, z_ranks, k_ranks) -> dict:
    reml_ranks = {row["id"]: row["rank"] for row in ordered}
    moves = [abs(raw_ranks[row["id"]] - row["rank"]) for row in ordered]
    z_moves = [abs(z_ranks[key] - reml_ranks[key]) for key in z_ranks if key in reml_ranks]
    return {
        "kendall_reml_vs_raw": kendall_tau_b(reml_ranks, raw_ranks),
        "kendall_z_vs_raw": kendall_tau_b(z_ranks, {key: raw_ranks[key] for key in z_ranks}),
        "kendall_k10_vs_raw": kendall_tau_b(k_ranks, raw_ranks),
        "mean_abs_rank_move_reml": float(np.mean(moves)) if moves else None,
        "max_abs_rank_move_reml": int(max(moves)) if moves else None,
        "max_abs_rank_move_z": int(max(z_moves)) if z_moves else None,
        "top5_reml": [row["id"] for row in ordered[:5]],
        "top5_raw": [pid for pid, _rank in sorted(raw_ranks.items(), key=lambda item: item[1])[:5]],
        "top5_k10": [pid for pid, _rank in sorted(k_ranks.items(), key=lambda item: item[1])[:5]],
    }


def _sensitivity(x, z, y, projects, ordered, lam_hat) -> list[dict]:
    points = []
    seen = set()
    grid = [5.0, 10.0, lam_hat, 20.0, 30.0, 50.0]
    base_top = [row["id"] for row in ordered[:5]]
    for lam in grid:
        key = round(lam, 6)
        if key in seen:
            continue
        seen.add(key)
        beta, _sigma2, _cov, llf = _effects_at(x, z, y, lam)
        effect = {project: float(beta[i]) for i, project in enumerate(projects)}
        ranking = sorted(projects, key=lambda project: (-effect[project], project))
        top = ranking[:5]
        points.append(
            {
                "lambda": lam,
                "loglik": llf,
                "top5": top,
                # The same five projects, in any order (the column is labelled "Same top 5").
                "top5_same": set(top) == set(base_top),
                "is_hat": abs(lam - lam_hat) < 1e-9,
            }
        )
    return points


def _lojo(reviews, weights, projects, top5: list[str]) -> list[dict]:
    judges = sorted({review["judge_id"] for review in reviews})
    rows = []
    base = set(top5)
    for judge in judges:
        kept = [review for review in reviews if review["judge_id"] != judge]
        if len({review["project_id"] for review in kept}) < 2:
            rows.append({"judge_id": judge, "top5_changed": None, "top5": [], "note": "too few projects"})
            continue
        project_ids, judge_ids, y, _projects, _judges, x, z = _fit_arrays(kept, weights)
        chosen = choose_lambda(x, z, y)
        effect = {project: float(chosen["beta"][i]) for i, project in enumerate(_projects)}
        ranking = sorted(effect, key=lambda project: (-effect[project], project))
        top = ranking[:5]
        rows.append(
            {
                "judge_id": judge,
                "top5_changed": set(top) != base,
                "top5": top,
                "note": "",
            }
        )
    return rows


def judge_leans(judge_ids, y, resid, lam: float, present: set, flags: dict) -> list[dict]:
    """Each judge's estimated lean at λ̂: the BLUP b̂ = g Zᵀ H⁻¹ r with g = 1/λ.

    Each review has one judge, so ZᵀZ is diagonal and b̂_j = Σ r_i / (λ + n_j) over judge j's
    reviews, where r = y − X â. A judge with few reviews is pulled towards 0: one review is not
    evidence of a lean. This is what the adjusted score removes.
    """
    totals: dict[str, list[float]] = defaultdict(list)
    residuals: dict[str, float] = defaultdict(float)
    for judge, value, r in zip(judge_ids, y, resid):
        totals[judge].append(float(value))
        residuals[judge] += float(r)
    rows = []
    for judge in sorted(set(totals) | set(present)):
        n = len(totals.get(judge, []))
        lean = residuals[judge] / (lam + n) if n else None
        rows.append(
            {
                "judge_id": judge,
                "n": n,
                "mean_total": (sum(totals[judge]) / n) if n else None,
                "lean": lean,
                "flags": " ".join(sorted(key for key, who in flags.items() if key != "short_projects" and judge in who)),
            }
        )
    return rows


def _flags(reviews, projects_meta, z_rows, judges_present, n_reviews) -> dict:
    per_judge = defaultdict(int)
    values_by_judge: dict[str, set] = defaultdict(set)
    for review in reviews:
        per_judge[review["judge_id"]] += 1
        values_by_judge[review["judge_id"]].update(review["criteria"].values())
    # Straight line: one value on every criterion of every review (4/4/4, 4/4/4). A judge whose
    # totals merely repeat (3/5/3 and 5/4/2 both total 11/3) is flagged separately, not as this.
    straight = sorted(
        judge for judge, values in values_by_judge.items() if per_judge[judge] >= 2 and len(values) == 1
    )
    flat_totals = sorted(row["judge_id"] for row in z_rows if row["reason"] == "sd=0")
    zero = sorted(judges_present - set(per_judge))
    one = sorted(judge for judge, n in per_judge.items() if n == 1)
    few = sorted(set(zero) | {judge for judge, n in per_judge.items() if n <= 2})
    short = sorted(project for project, n in n_reviews.items() if n < 3)
    return {
        "straight_line": straight,
        "no_total_variance": flat_totals,
        "zero_counted": zero,
        "one_counted": one,
        "at_most_two": few,
        "short_projects": short,
    }


def rank_project(snapshot: dict, project_id: str) -> int | None:
    for row in snapshot.get("rows") or []:
        if row["id"] == project_id:
            return row["rank"]
    return None
