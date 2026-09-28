"""Checks shared by the write services: the event exists, and published results stay frozen."""

from __future__ import annotations

from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import Event
from samepage.core.errors import Conflict

FROZEN = ("published", "archived")


def event_or_404(event_id: str, *, lock: bool = False) -> Event:
    rows = Event.objects.filter(id=event_id)
    if lock:
        rows = rows.select_for_update()
    event = rows.first()
    if event is None:
        raise NotFound("Unknown event.")
    return event


def refuse_if_published(event: Event | str) -> None:
    """After publish, nothing that feeds the ranking may change: scores, weights, duplicates, assignments."""
    state = event.state if isinstance(event, Event) else Event.objects.filter(id=event).values_list("state", flat=True).first()
    if state in FROZEN:
        raise Conflict("Results are published, so the inputs to the ranking are frozen.")
