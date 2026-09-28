"""Deadline comparisons against one clock. The database trigger is the second copy."""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def closed_message(close_at: datetime) -> str:
    stamp = as_utc(close_at).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"submissions closed at {stamp}"


def is_closed(now: datetime, close_at: datetime) -> bool:
    return as_utc(now) > as_utc(close_at)


def import_row_allowed(submitted_at: datetime | None, close_at: datetime) -> bool:
    """Imports are refused only when the row's own submitted_at is after close."""
    if submitted_at is None:
        return True
    return as_utc(submitted_at) <= as_utc(close_at)
