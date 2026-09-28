"""The grid and the deduplicated fixture. Research cross-checks, not golden copies of a hidden file."""

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
