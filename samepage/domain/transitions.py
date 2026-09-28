"""State machines. Callers hold the row lock; this function only names legal moves."""

from __future__ import annotations

EVENT = {
    "draft": {"open"},
    "open": {"closed"},
    "closed": {"judging"},
    "judging": {"published"},
    "published": {"archived"},
    "archived": set(),
}

SUBMISSION = {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"locked", "withdrawn"},
    "locked": set(),
    "withdrawn": set(),
}

SCORE = {
    "draft": {"final"},
    "final": {"unlocked"},
    "unlocked": {"final"},
}

BATCH = {
    "issued": {"in_progress", "abandoned"},
    "in_progress": {"done", "abandoned"},
    "done": set(),
    "abandoned": set(),
}

DUPLICATE = {
    "provisional": {"confirmed"},
    "confirmed": {"confirmed"},
}

MACHINES = {
    "event": EVENT,
    "submission": SUBMISSION,
    "score": SCORE,
    "batch": BATCH,
    "duplicate": DUPLICATE,
}


class TransitionError(ValueError):
    pass


def transition(machine: str, current: str, target: str) -> str:
    allowed = MACHINES[machine].get(current)
    if allowed is None or target not in allowed:
        raise TransitionError(f"{machine} cannot go from {current} to {target}")
    return target
