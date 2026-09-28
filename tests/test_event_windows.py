"""A draft event is its organizers' until it opens, and 'Judging ends' is enforced."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import Assignment, Event, Person, ScoreRev, Team, TeamMember
from samepage.core.errors import Conflict

pytestmark = [needs_db, pytest.mark.django_db]


def _signed_in(person: Person) -> Client:
    browser = Client()
    browser.force_login(person)
    return browser


# --- a draft event is its organizers' until it opens ---------------------------------------------


def test_a_draft_event_is_not_found_by_id_for_anyone_but_its_staff(client, bearer):
    created = client.post(
        "/e.json",
        {"name": "Quiet draft", "submissions_close": "2031-01-01T00:00:00Z", "tracks": ["A"]},
        content_type="application/json",
        **bearer("admin"),
    )
    event_id = created.json()["id"]
    visitor = _signed_in(Person.objects.create_user("draft.visitor@example.org", password="draft visitor pw"))
    for path in (f"/e/{event_id}.json", f"/e/{event_id}/projects.json", f"/e/{event_id}/criteria.json", f"/e/{event_id}"):
        assert Client().get(path).status_code == 404, path
        assert visitor.get(path).status_code == 404, path
        assert client.get(path, **bearer("admin")).status_code == 200, path
    # Same answer as an id that was never created.
    assert Client().get("/e/evt_nothere.json").status_code == 404
    # No team can start before the organizer opens the event.
    assert visitor.post(f"/e/{event_id}/teams.json", {"name": "Early birds"}, content_type="application/json").status_code == 404
    assert not Team.objects.filter(event_id=event_id).exists()
    from samepage.services import teams

    with pytest.raises(Conflict):
        teams.create(event_id, Person.objects.get(email="draft.visitor@example.org"), {"name": "Early birds"})
    # Once open, it is public.
    assert client.post(f"/e/{event_id}/state.json", {"state": "open"}, content_type="application/json", **bearer("admin")).status_code == 200
    assert Client().get(f"/e/{event_id}.json").status_code == 200
    assert visitor.post(f"/e/{event_id}/teams.json", {"name": "Early birds"}, content_type="application/json").status_code == 201
    assert TeamMember.objects.filter(event_id=event_id).count() == 1


# --- judging ends --------------------------------------------------------------------------------


def test_scores_are_refused_after_judging_ends_until_the_organizer_extends_it(client, bearer):
    open_row = Assignment.objects.filter(judge_id="jdg_08", submission__event_id="evt_01", finalized_at__isnull=True).first()
    project = open_row.submission_id
    url = f"/e/evt_01/judge/assignments/{project}/finalize.json"
    body = {"criteria": {"functionality": 4, "quality": 4, "innovation": 4}}
    Event.objects.filter(id="evt_01").update(judging_ends=timezone.now() - timedelta(minutes=1))
    revs = ScoreRev.objects.count()
    late = client.post(url, body, content_type="application/json", **bearer("jdg08"))
    assert late.status_code == 409 and "Judging ended at" in late.json()["detail"]
    draft = client.post(f"/e/evt_01/judge/assignments/{project}/scores.json", body, content_type="application/json", **bearer("jdg08"))
    assert draft.status_code == 409
    assert ScoreRev.objects.count() == revs
    assert "Judging ends" in client.get(f"/e/evt_01/judge/assignments/{project}", **bearer("jdg08")).content.decode("utf-8")
    later = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    moved = client.post("/e/evt_01/settings.json", {"judging_ends": later}, content_type="application/json", **bearer("org"))
    assert moved.status_code == 200, moved.content
    assert client.post(url, body, content_type="application/json", **bearer("jdg08")).status_code == 200
