"""One whole event through the HTML pages, the way DEMO.md walks it, with CSRF enforced.

Every write is the form a page renders, posted with that page's CSRF token, by a browser that is
signed in with a session cookie, never a bearer token. Each step first opens the page that holds
the form and checks the form is there, so a missing button or a broken page fails the test.
The one shortcut: the deadline passes by moving it into the past in the database, instead of
waiting for it (tools/lifecycle_check.py waits for a real one in CI).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import Event, Person, Submission, Track

pytestmark = [needs_db, pytest.mark.django_db]

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


class Browser:
    """A cookie session with CSRF checks on, like a real browser against the portal."""

    def __init__(self):
        self.client = Client(enforce_csrf_checks=True)

    def open(self, path: str, status: int = 200, *, has: str | None = None) -> str:
        response = self.client.get(path)
        assert response.status_code == status, (path, response.status_code, response.content[:500])
        text = response.content.decode("utf-8")
        if has is not None:
            assert has in text, f"{path} has no {has!r}"
        return text

    def post(self, path: str, fields: dict | None = None, status: int = 303) -> tuple[str, str]:
        """Post a form with the CSRF token the last page set. Returns (Location, body)."""
        data = dict(fields or {})
        data["csrfmiddlewaretoken"] = self.client.cookies["csrftoken"].value
        response = self.client.post(path, data)
        assert response.status_code == status, (path, response.status_code, response.content[:800])
        return response.get("Location", ""), response.content.decode("utf-8")


def _form(action: str) -> str:
    return f'action="{action}"'


def _link(page: str, kind: str) -> str:
    """The one-time link a page shows in its read-only field, as a path."""
    found = re.search(r'value="https?://[^/"]+(/' + kind + r'/[^"]+)"', page)
    assert found, f"no /{kind}/ link on the page"
    return found.group(1)


def _csv(browser: Browser, path: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(browser.open(path))))


def _sign_up(email: str, name: str) -> Browser:
    browser = Browser()
    browser.open("/signup", has=_form("/signup"))
    location, _ = browser.post("/signup", {"name": name, "email": email, "password": f"{name} password 123"})
    assert location == "/"
    return browser


def test_a_whole_event_through_the_html_forms():
    stranger = Browser()

    # 1. The admin creates the event from the home page and opens it.
    admin = Browser()
    admin.open("/demo/enter/admin", has=_form("/demo/enter/admin"))
    admin.post("/demo/enter/admin")
    admin.open("/", has='href="/e/new"')
    admin.open("/e/new", has=_form("/e"))
    close = (timezone.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    location, _ = admin.post(
        "/e",
        {
            "name": "Browser Hack",
            "submissions_close": close,
            "tracks": "Tools\nClimate",
            "prizes": "Grand prize",
            "criteria": "Impact: 2\nCraft: 1",
            "custom_questions": "License: MIT, Apache-2.0*",
            "max_team_size": "3",
        },
    )
    event_id = re.fullmatch(r"/e/(evt_[0-9a-f]+)/settings", location).group(1)
    assert Event.objects.get(id=event_id).state == "draft"
    admin.open(location, has=_form(f"/e/{event_id}/state"))
    admin.post(f"/e/{event_id}/state", {"state": "open"})
    tools = Track.objects.get(event_id=event_id, name="Tools").id

    # 2. A participant signs up, starts a team and invites a friend by link.
    lead = _sign_up("lead@example.org", "Lead")
    lead.open(f"/e/{event_id}", has=_form(f"/e/{event_id}/teams"))
    location, _ = lead.post(f"/e/{event_id}/teams", {"name": "Lanterns"})
    team_id = location.rsplit("/", 1)[1]
    lead.open(location, has=_form(f"/e/{event_id}/teams/{team_id}/invites"))
    _, page = lead.post(f"/e/{event_id}/teams/{team_id}/invites", {"max_uses": "1", "days": "7"}, status=201)
    join = _link(page, "join")
    friend = _sign_up("friend@example.org", "Friend")
    friend.open(join, has=_form(join))
    location, _ = friend.post(join)
    assert location == f"/e/{event_id}/teams/{team_id}"
    lead.open(location, has="friend@example.org")

    # 3. A draft, an image, an edit that answers the required question, then submit.
    lead.open(f"/e/{event_id}/projects/new", has=_form(f"/e/{event_id}/projects"))
    location, _ = lead.post(
        f"/e/{event_id}/projects", {"title": "Night Shift", "tagline": "Lights", "track": tools, "tech_tags": "python django"}
    )
    project_id = location.rsplit("/", 1)[1]
    assert Submission.objects.get(id=project_id).state == "draft"
    assert project_id not in stranger.open(f"/e/{event_id}/projects")
    lead.open(f"/e/{event_id}/projects/{project_id}/edit", has=_form(f"/e/{event_id}/projects/{project_id}/media"))
    lead.post(
        f"/e/{event_id}/projects/{project_id}/media",
        {"kind": "thumbnail", "file": SimpleUploadedFile("t.png", PNG, content_type="image/png")},
    )
    page = lead.open(location, has=_form(f"/e/{event_id}/projects/{project_id}/submit"))
    lead.post(f"/e/{event_id}/projects/{project_id}/submit", status=422)  # the license is not answered yet
    lead.post(
        f"/e/{event_id}/projects/{project_id}",
        {"title": "Night Shift", "tagline": "Lights", "track": tools, "tech_tags": "python django", "q_license": "MIT"},
    )
    lead.post(f"/e/{event_id}/projects/{project_id}/submit")
    assert "Night Shift" in stranger.open(f"/e/{event_id}/projects?tag=django")
    assert "Night Shift" not in stranger.open(f"/e/{event_id}/projects?tag=rust")

    # 4. Two judges invited by email choose their passwords with the one-time links.
    judges = []
    for index in (1, 2):
        admin.open(f"/e/{event_id}/settings", has=_form(f"/e/{event_id}/people"))
        _, page = admin.post(
            f"/e/{event_id}/people", {"email": f"judge{index}@example.org", "role": "judge"}, status=201
        )
        link = _link(page, "password")
        judge = Browser()
        judge.open(link, has=_form(link))
        location, _ = judge.post(link, {"password": f"judge {index} password"})
        assert location == "/account"
        judges.append((Person.objects.get(email=f"judge{index}@example.org").id, judge))

    # 5. The deadline passes: an edit is refused; the event moves to judging; batches are issued.
    Event.objects.filter(id=event_id).update(submissions_close=timezone.now() - timedelta(seconds=1))
    _, page = lead.post(f"/e/{event_id}/projects/{project_id}", {"title": "Too late", "track": tools}, status=409)
    assert "submissions closed at" in page
    assert Submission.objects.get(id=project_id).title == "Night Shift"
    for state in ("closed", "judging"):
        admin.open(f"/e/{event_id}/settings", has=f"Move to {state}")
        admin.post(f"/e/{event_id}/state", {"state": state})
    admin.open(f"/e/{event_id}/progress", has=_form(f"/e/{event_id}/assignment-runs"))
    location, _ = admin.post(f"/e/{event_id}/assignment-runs", {"kind": "initial", "coverage": "2", "cap": "12"})
    admin.open(location, has="initial")

    # 6. Each judge saves a draft, which is not counted, then finalizes from the console.
    console = f"/e/{event_id}/judge/assignments/{project_id}"
    for index, (judge_id, judge) in enumerate(judges):
        judge.open(f"/e/{event_id}/judge/batches", has=console)
        judge.open(console, has=_form(f"{console}/scores"))
        judge.post(f"{console}/scores", {"c_impact": "3", "c_craft": "3", "comment": "first look"})
        rows = _csv(admin, f"/e/{event_id}/scores.csv")
        mine = [row for row in rows if row["judge_id"] == judge_id]
        assert [(row["counted"], row["excluded_reason"]) for row in mine] == [("false", "not_final:draft")]
        judge.open(console, has="not yet final")
        judge.post(f"{console}/finalize", {"c_impact": str(4 + index), "c_craft": "2", "comment": "done"})
        judge.open(console, has="final")
        judge.open(f"/e/{event_id}/judges/{judges[1 - index][0]}/scores", status=403)
        judge.open(f"/e/{event_id}/judges/me/scores", has="done")

    rows = _csv(admin, f"/e/{event_id}/scores.csv")
    # Impact 2 : Craft 1. Judge 1 gave 4 and 2 (10/3), judge 2 gave 5 and 2 (4).
    assert sorted(round(float(row["weighted_total"]), 3) for row in rows if row["counted"] == "true") == [3.333, 4.0]

    # 7. The organizer changes a weight: the weighted totals follow, and the results refit on read.
    admin.open(f"/e/{event_id}/settings", has=_form(f"/e/{event_id}/criteria"))
    admin.post(f"/e/{event_id}/criteria", {"weight_impact": "1", "weight_craft": "1", "label_impact": "Impact", "label_craft": "Craft"})
    rows = _csv(admin, f"/e/{event_id}/scores.csv")
    assert sorted(float(row["weighted_total"]) for row in rows if row["counted"] == "true") == [3.0, 3.5]
    admin.open(f"/e/{event_id}/progress", has="2 counted")

    # 8. Publish. The results are public and frozen: a late finalize is refused.
    stranger.open(f"/e/{event_id}/results", status=403)
    admin.open(f"/e/{event_id}/results", has=_form(f"/e/{event_id}/publish"))
    admin.post(f"/e/{event_id}/publish")
    assert "Night Shift" in stranger.open(f"/e/{event_id}/results")
    judge = judges[0][1]
    judge.open(console)
    judge.post(f"{console}/finalize", {"c_impact": "1", "c_craft": "1"}, status=409)
    assert Event.objects.get(id=event_id).state == "published"
