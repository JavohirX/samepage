"""Outside oracle: statsmodels re-derives the published ranking from scores.csv.

Runs in the oracle image (`docker compose --profile oracle run --rm oracle`), never in the
portal image, or natively with `pip install -r requirements-oracle.txt`.

1. Downloads /e/<event>/scores.csv with the organizer token from .dogfood.toml and keeps the
   rows with counted=true. A review of a project merged into another counts for the target.
2. Builds statsmodels' own MixedLM (y ~ 0 + C(project), one random intercept per judge) and
   evaluates its REML log-likelihood, with the fixed effects profiled out, on the λ grid in
   JUDGING.md. The grid is ours. The likelihood and the GLS effects are statsmodels'.
3. Ranks the projects by statsmodels' effects at its own λ̂ and compares with the portal's
   /e/<event>/results.json: λ, every project's review count, every displayed adjusted score,
   every rank, and ranking_sha256.

Exit status 0 means every comparison matched. Any mismatch prints the first differences and
exits 1. Nothing here imports Samepage code.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import sys
import urllib.request
from fractions import Fraction

import numpy as np
import pandas as pd
import statsmodels
import statsmodels.formula.api as smf
from statsmodels.regression.mixed_linear_model import MixedLMParams

CRITERIA = ("c_functionality", "c_quality", "c_innovation")


def load_toml(path: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        tomllib = None
    if tomllib:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    data, section = {}, None
    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1], {})
            continue
        key, _, value = line.partition("=")
        section[key.strip()] = value.strip().strip('"')
    return data


def fetch(base: str, path: str, token: str) -> bytes:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        headers={"Authorization": token, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def counted_reviews(csv_bytes: bytes) -> tuple[pd.DataFrame, str]:
    """Counted rows as (project, judge, y). y is the mean of the three criteria when that equals
    the CSV's weighted_total (equal weights), else weighted_total itself."""
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    rows = []
    equal_weights = True
    for row in reader:
        if row["counted"].strip().lower() != "true":
            continue
        project = row["merged_into"].strip() or row["project_id"].strip()
        values = [Fraction(row[column]) for column in CRITERIA]
        mean = sum(values, Fraction(0)) / len(values)
        stated = Fraction(row["weighted_total"])
        if abs(float(mean - stated)) > 1e-9:
            equal_weights = False
        rows.append({"project": project, "judge": row["judge_id"].strip(), "mean": float(mean), "stated": float(stated)})
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SystemExit("oracle: scores.csv has no counted rows")
    source = "mean of the three criterion columns (equals weighted_total on every row)"
    frame["y"] = frame["mean"]
    if not equal_weights:
        frame["y"] = frame["stated"]
        source = "weighted_total column (criteria are not equally weighted)"
    return frame[["project", "judge", "y"]], source


def grid() -> tuple[list[float], callable]:
    stage1 = [math.exp(math.log(0.1) + 0.05 * k) for k in range(185)]

    def stage2(t1: float) -> list[float]:
        return [math.exp(t1 + 0.001 * m) for m in range(-50, 51)]

    return stage1, stage2


def statsmodels_fit(frame: pd.DataFrame) -> dict:
    model = smf.mixedlm("y ~ 0 + C(project)", frame, groups=frame["judge"])
    # MixedLM.fit() sets these before it calls loglike(); we call loglike() on our grid instead.
    model.reml = True
    model.cov_pen = None
    model.fe_pen = None
    model._cov_sing = 0

    def loglike(lam: float) -> float:
        # cov_re is the judge variance relative to the residual scale: τ²/σ² = 1/λ.
        params = MixedLMParams.from_components(fe_params=np.zeros(model.k_fe), cov_re=np.array([[1.0 / lam]]))
        return float(model.loglike(params, profile_fe=True))

    stage1, stage2 = grid()
    best_ll, best_lam, best_index, t1 = -math.inf, None, None, None
    for index, lam in enumerate(stage1):
        value = loglike(lam)
        if value > best_ll:
            best_ll, best_lam, best_index, t1 = value, lam, index, math.log(lam)
    for offset, lam in enumerate(stage2(t1)):
        value = loglike(lam)
        if value > best_ll:
            best_ll, best_lam, best_index = value, lam, len(stage1) + offset
    fe_params, singular = model.get_fe_params(np.array([[1.0 / best_lam]]), np.array([]))
    effects = {}
    for name, value in zip(model.exog_names, fe_params):
        # Patsy names the columns C(project)[prj_01], C(project)[prj_02], ...
        project = name[name.index("[") + 1 : name.rindex("]")]
        effects[project] = float(value)
    return {
        "lambda": best_lam,
        "loglik": best_ll,
        "index": best_index,
        "evaluations": len(stage1) + 101,
        "effects": effects,
        "singular": bool(singular),
    }


def ranking_sha256(lines: list[tuple[str, int]]) -> str:
    body = "".join(f"{project},{rank}\n" for project, rank in lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compare(fit: dict, frame: pd.DataFrame, results: dict) -> tuple[list[str], dict]:
    problems = []
    items = results.get("items") or []
    portal = {item["id"]: item for item in items}
    n_reviews = frame.groupby("project").size().to_dict()
    effects = fit["effects"]
    if set(portal) != set(effects):
        missing = sorted(set(effects) - set(portal))
        extra = sorted(set(portal) - set(effects))
        problems.append(f"project sets differ: only in scores.csv {missing}, only in results.json {extra}")
    portal_lambda = results.get("lambda")
    if portal_lambda is None or abs(float(portal_lambda) - fit["lambda"]) > 1e-9 * fit["lambda"]:
        problems.append(f"lambda differs: statsmodels {fit['lambda']!r}, portal {portal_lambda!r}")
    worst = 0.0
    for project, effect in effects.items():
        item = portal.get(project)
        if item is None:
            continue
        if int(item["n_reviews"]) != int(n_reviews[project]):
            problems.append(f"{project}: n_reviews portal {item['n_reviews']}, scores.csv {n_reviews[project]}")
        shown = float(item["adjusted"])
        gap = abs(round(effect, 3) - shown)
        worst = max(worst, abs(effect - shown))
        if gap > 1e-9:
            problems.append(f"{project}: adjusted portal {item['adjusted']}, statsmodels {effect:.6f}")
    # Rank by statsmodels' effect. Effects equal to 1e-9 (for example two projects with the same
    # judges and the same scores) form a tie group. The portal orders a tie group by its
    # documented tie-breaks (P(top-5), then reviews, then submission time); the oracle does not
    # recompute P(top-5), so it checks that the group holds the same rank positions on both sides
    # and takes the order inside the group from the portal.
    ordered = sorted(effects, key=lambda project: (-effects[project], project))
    groups: list[list[str]] = []
    for project in ordered:
        if groups and abs(effects[groups[-1][-1]] - effects[project]) <= 1e-9:
            groups[-1].append(project)
        else:
            groups.append([project])
    final: list[str] = []
    tie_groups = []
    for group in groups:
        start = len(final) + 1
        positions = set(range(start, start + len(group)))
        if len(group) > 1:
            tie_groups.append(group)
            portal_ranks = {int(portal[project]["rank"]) for project in group if project in portal}
            if portal_ranks != positions:
                problems.append(f"tie group {group}: statsmodels ranks {sorted(positions)}, portal {sorted(portal_ranks)}")
            group = sorted(group, key=lambda project: int(portal[project]["rank"]) if project in portal else 0)
        final.extend(group)
    oracle_lines = [(project, rank) for rank, project in enumerate(final, start=1)]
    oracle_sha = ranking_sha256(oracle_lines)
    for project, rank in oracle_lines:
        item = portal.get(project)
        if item is not None and int(item["rank"]) != rank:
            problems.append(f"{project}: rank portal {item['rank']}, statsmodels {rank}")
            break
    if oracle_sha != results.get("ranking_sha256"):
        problems.append(f"ranking_sha256 differs: statsmodels {oracle_sha}, portal {results.get('ranking_sha256')}")
    return problems, {"oracle_sha": oracle_sha, "max_abs_vs_3dp": worst, "top5": final[:5], "tie_groups": tie_groups}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--toml", default=".dogfood.toml")
    parser.add_argument("--base", default=None, help="portal URL; defaults to base_url in the toml")
    parser.add_argument("--event", default="evt_01")
    args = parser.parse_args()
    config = load_toml(args.toml)
    base = args.base or config["portal"]["base_url"]
    _name, _sep, token = config["auth"]["organizer"].partition(":")
    token = token.strip()

    csv_bytes = fetch(base, f"/e/{args.event}/scores.csv", token)
    results_bytes = fetch(base, f"/e/{args.event}/results.json", token)
    results = json.loads(results_bytes.decode("utf-8"))
    frame, source = counted_reviews(csv_bytes)
    fit = statsmodels_fit(frame)
    problems, summary = compare(fit, frame, results)

    print("Samepage statsmodels oracle")
    print(f"portal: {base} event {args.event}")
    print(f"python {platform.python_version()}, statsmodels {statsmodels.__version__}, numpy {np.__version__}, pandas {pd.__version__}")
    print(f"scores.csv sha256 {hashlib.sha256(csv_bytes).hexdigest()}")
    print(f"counted rows {len(frame)}, projects {frame['project'].nunique()}, judges {frame['judge'].nunique()}")
    print(f"y: {source}")
    print(
        f"statsmodels REML on the JUDGING.md grid ({fit['evaluations']} points): "
        f"argmax index {fit['index']}, lambda {fit['lambda']!r}, loglik {fit['loglik']:.10f}"
    )
    print(f"portal results.json: method {results.get('method')}, lambda {results.get('lambda')!r}")
    print(f"max |statsmodels effect - portal adjusted (3 dp)| {summary['max_abs_vs_3dp']:.6f}")
    print(f"statsmodels top 5: {' '.join(summary['top5'])}")
    for group in summary["tie_groups"]:
        print(f"tie group (equal effects, order inside taken from the portal): {' '.join(group)}")
    print(f"ranking_sha256 statsmodels {summary['oracle_sha']}")
    print(f"ranking_sha256 portal      {results.get('ranking_sha256')}")
    if problems:
        print(f"FAIL: {len(problems)} difference(s)")
        for line in problems[:20]:
            print(f"  - {line}")
        return 1
    print("PASS: statsmodels reproduces lambda, every adjusted score, every rank and ranking_sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
