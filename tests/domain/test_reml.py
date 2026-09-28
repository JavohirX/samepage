"""Engine refit of the deduplicated fixture: the grid's λ, the top-5 set, Dry Harbour's rank, short projects."""

import json
from pathlib import Path

from samepage.engine.cli import load_counted
from samepage.engine.snapshot import build_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_deduplicated_fixture_matches_the_method():
    reviews, meta, weights = load_counted(ROOT / "fixtures.json")
    snapshot = build_snapshot(reviews, meta, weights, with_lojo=False, with_draws=False)
    assert snapshot["n_projects"] == 40
    assert snapshot["n_reviews"] == 121
    assert abs(snapshot["lambda"] - 15.3239) < 1e-3
    assert set(snapshot["top5"]) == {"prj_10", "prj_11", "prj_25", "prj_34", "prj_37"}
    assert snapshot["dense_max_abs"] < 1e-9
    harbour = next(row for row in snapshot["rows"] if row["id"] == "prj_41")
    assert harbour["rank"] == 9
    assert snapshot["flags"]["short_projects"] == [
        "prj_10",
        "prj_15",
        "prj_18",
        "prj_19",
        "prj_24",
        "prj_29",
        "prj_39",
        "prj_40",
    ]


def test_fixture_file_is_the_official_one():
    payload = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    assert payload["projects"][0]["title"] == "Glass Signal"
    assert payload["event"]["submissions_close"] == "2026-03-01T18:00:00Z"
    assert len(payload["scores"]) == 126


def test_judge_leans_are_the_blup_and_match_a_dense_inverse():
    import numpy as np

    from samepage.engine.reml import design

    reviews, meta, weights = load_counted(ROOT / "fixtures.json")
    snapshot = build_snapshot(reviews, meta, weights, with_lojo=False, with_draws=False)
    lam = snapshot["lambda"]
    # Dense BLUP: b = g Zᵀ (I + g Z Zᵀ)⁻¹ (y − X â), with â the published adjusted scores.
    from samepage.engine.snapshot import _fit_arrays

    project_ids, judge_ids, y, projects, judges, x, z = _fit_arrays(reviews, weights)
    beta = np.array([next(row["adjusted"] for row in snapshot["rows"] if row["id"] == p) for p in projects])
    g = 1.0 / lam
    dense = g * z.T @ np.linalg.inv(np.eye(len(y)) + g * (z @ z.T)) @ (y - x @ beta)
    by_judge = {row["judge_id"]: row for row in snapshot["judge_leans"]}
    for index, judge in enumerate(judges):
        assert abs(by_judge[judge]["lean"] - dense[index]) < 1e-9
    # The straight-line judge (4/4/4 on everything) keeps full weight; their lean is small and positive.
    assert abs(by_judge["jdg_07"]["lean"] - 0.0665) < 1e-3 and "straight_line" in by_judge["jdg_07"]["flags"]
    # One review is not evidence of a lean, so jdg_23's is pulled close to 0.
    assert abs(by_judge["jdg_23"]["lean"] + 0.0280) < 1e-3 and by_judge["jdg_23"]["n"] == 1
    largest = max((row for row in snapshot["judge_leans"] if row["lean"] is not None), key=lambda row: abs(row["lean"]))
    assert largest["judge_id"] == "jdg_02" and abs(largest["lean"] - 0.1437) < 1e-3
    # Every judge who scored has a lean.
    assert sum(1 for row in snapshot["judge_leans"] if row["lean"] is not None) == len(judges)
