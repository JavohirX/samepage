from datetime import datetime, timezone
from fractions import Fraction

import pytest

from samepage.domain.deadline import closed_message, import_row_allowed, is_closed
from samepage.domain.transitions import TransitionError, transition
from samepage.domain.weighted import weighted_total


def test_weighted_total_is_exact():
    total = weighted_total(
        {"functionality": 2, "quality": 4, "innovation": 2},
        {"functionality": 1, "quality": 1, "innovation": 1},
    )
    assert total == Fraction(8, 3)


def test_weight_must_be_positive():
    with pytest.raises(ValueError):
        weighted_total({"functionality": 3}, {"functionality": 0})


def test_deadline_message_uses_zulu():
    close = datetime(2026, 3, 1, 18, 0, tzinfo=timezone.utc)
    assert closed_message(close) == "submissions closed at 2026-03-01T18:00:00Z"
    assert is_closed(datetime(2026, 9, 27, tzinfo=timezone.utc), close)
    assert import_row_allowed(datetime(2026, 2, 1, tzinfo=timezone.utc), close)
    assert not import_row_allowed(datetime(2026, 3, 2, tzinfo=timezone.utc), close)


def test_event_publish_only_from_judging():
    assert transition("event", "judging", "published") == "published"
    with pytest.raises(TransitionError):
        transition("event", "open", "published")


def test_score_can_be_unlocked_and_finalised_again():
    assert transition("score", "final", "unlocked") == "unlocked"
    assert transition("score", "unlocked", "final") == "final"
