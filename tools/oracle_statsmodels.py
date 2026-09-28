"""Outside oracle. Runs in the oracle image, never in the portal image.

Downloads scores.csv with the organizer token, then asks statsmodels for its own
REML likelihood on the JUDGING.md grid. The grid is ours. The likelihood is not.
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import sys
import urllib.request

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf


def load_toml(path: str) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None
    if tomllib:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    data, section = {}, None
    for raw in open(path, encoding="utf-8"):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1], {})
            continue
        key, _, value = line.partition("=")
        section[key.strip()] = value.strip().strip('"')
    return data


def stage1():
    return [math.exp(math.log(0.1) + 0.05 * k) for k in range(185)]


def download(base: str, token: str) -> pd.DataFrame:
    request = urllib.request.Request(
        base.rstrip("/") + "/e/evt_01/scores.csv?counted=true",
        headers={"Authorization": token},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8")
    frame = pd.read_csv(io.StringIO(text))
    frame = frame[frame["counted"].astype(str) == "true"].copy()
    frame["y"] = frame["weighted_total"].astype(float)
    frame["project"] = frame["project_id"].astype(str)
    frame["judge"] = frame["judge_id"].astype(str)
    return frame


def likelihood_on_grid(frame: pd.DataFrame) -> tuple[float, int, object]:
    """Return (lambda, argmax index, fitted result at that lambda)."""
    model = smf.mixedlm("y ~ 0 + C(project)", frame, groups=frame["judge"])
    start = np.zeros(model.k_fe + 1)
    # The last parameter is the log of the random-intercept standard deviation in recent statsmodels.
    best = None
    grid = []
    t1 = None
    best_ll = -np.inf
    for index, lam in enumerate(stage1()):
        grid.append(lam)
        llf = _llf(model, start, lam)
        if llf > best_ll:
            best_ll = llf
            t1 = math.log(lam)
            best = index
    refined = [math.exp(t1 + 0.001 * m) for m in range(-50, 51)]
    chosen_index = best
    chosen = grid[best]
    for offset, lam in enumerate(refined):
        llf = _llf(model, start, lam)
        if llf > best_ll:
            best_ll = llf
            chosen = lam
            chosen_index = len(grid) + offset
    fit = model.fit(reml=True, start_params=_params(model, start, chosen), method="bfgs", maxiter=200)
    return chosen, chosen_index, fit


def _params(model, start, lam: float) -> np.ndarray:
    params = np.array(start, dtype=float, copy=True)
    # statsmodels stores the random-effect standard deviation as exp(param) relative to scale.
    # λ = σ²/τ², so τ/σ = 1/sqrt(λ). We set the last parameter to log(1/sqrt(λ)).
    params[-1] = math.log(1.0 / math.sqrt(lam))
    return params


def _llf(model, start, lam: float) -> float:
    try:
        return float(model.loglike(_params(model, start, lam), _profile=True))
    except Exception:
        return float("-inf")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--toml", default=".dogfood.toml")
    parser.add_argument("--base", default=None)
    args = parser.parse_args()
    config = load_toml(args.toml)
    base = args.base or config["portal"]["base_url"]
    _name, _sep, value = config["auth"]["organizer"].partition(":")
    token = value.strip()
    if not token.lower().startswith("bearer "):
        token = "Bearer " + token
    frame = download(base, token)
    default = smf.mixedlm("y ~ 0 + C(project)", frame, groups=frame["judge"]).fit(reml=True, method="bfgs")
    import statsmodels

    print(f"statsmodels {statsmodels.__version__} default fit converged={default.converged}")
    lam, index, fit = likelihood_on_grid(frame)
    print(f"statsmodels {statsmodels.__version__} REML log-likelihood on the JUDGING.md grid: argmax index = {index} (lambda {lam:.4f})")
    print(f"rows {len(frame)} projects {frame['project'].nunique()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"oracle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
