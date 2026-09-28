"""Judge flags on the fixture: a straight line is one value everywhere, not equal totals."""

from pathlib import Path

from samepage.engine.cli import load_counted
from samepage.engine.snapshot import build_snapshot

ROOT = Path(__file__).resolve().parents[2]


def test_straight_line_is_jdg_07_only_and_equal_totals_are_a_separate_flag():
    reviews, meta, weights = load_counted(ROOT / "fixtures.json")
    judges = sorted({review["judge_id"] for review in reviews} | {"jdg_01"})
    flags = build_snapshot(reviews, meta, weights, with_lojo=False, with_draws=False, judges_present=judges)["flags"]
    assert flags["straight_line"] == ["jdg_07"]
    assert "jdg_19" in flags["no_total_variance"]
    assert "jdg_19" not in flags["straight_line"]
    # jdg_01 scored only the withdrawn Dry Harbour row, so it has no counted review.
    assert flags["zero_counted"] == ["jdg_01"]
    assert len(flags["at_most_two"]) == 8
