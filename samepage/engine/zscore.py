"""Per-judge z-scores. Undefined when a judge has no variance or fewer than two scores."""

from __future__ import annotations

from collections import defaultdict

import numpy as np


def judge_z(judge_ids: list[str], y: np.ndarray):
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, judge in enumerate(judge_ids):
        grouped[judge].append(index)
    z = np.full(len(y), np.nan)
    rows = []
    for judge in sorted(grouped):
        idx = np.array(grouped[judge])
        values = y[idx]
        n = int(len(values))
        sd = float(values.std(ddof=1)) if n > 1 else float("nan")
        if n < 2 or not (sd > 0):
            reason = "n<2" if n < 2 else "sd=0"
            rows.append({"judge_id": judge, "n": n, "sd": None if sd != sd else sd, "status": "undefined", "reason": reason})
            continue
        z[idx] = (values - values.mean()) / sd
        rows.append({"judge_id": judge, "n": n, "sd": sd, "status": "ok", "reason": ""})
    return z, rows


def project_z_means(project_ids: list[str], z: np.ndarray, projects: list[str]):
    means = {}
    for project in projects:
        mask = np.array([pid == project for pid in project_ids])
        chunk = z[mask]
        usable = chunk[np.isfinite(chunk)]
        means[project] = float(usable.mean()) if len(usable) else None
    return means
