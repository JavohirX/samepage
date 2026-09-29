"""Tests for Package T3: Public comments, pre-moderation, escaping, and anti-abuse."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import Event, Person, ProjectComment, Submission, Team
from samepage.services.clock import db_now

pytestmark = [needs_db, pytest.mark.django_db]


def _setup_event_with_project(event_id="evt_cmt"):
    now = db_now()
    event = Event.objects.create(
        id=event_id,
        name="Comments Test Event",
        state="open",
        submissions_close=now + timedelta(days=2),
    )
    team = Team.objects.create(id=f"tm_{event_id}", event=event, name="Team Cmt")
    sub = Submission.objects.create(
        id=f"prj_{event_id}_01",
        event=event,
        team=team,
        track_id="trk_01",
        title="Project with Comments",
        state="submitted",
    )
    return event, sub


def test_comment_pre_moderation_and_approval(client, bearer):
    """S6: Pre-moderation: a comment is visible only after an organizer approves it."""
    event, sub = _setup_event_with_project("evt_mod")
    author = Person.objects.create_user("commenter@example.org", password="pw")
    c_author = Client()
    c_author.force_login(author)

    # 1. Author posts comment
    res = c_author.post(
        f"/e/{event.id}/projects/{sub.id}/comments.json",
        {"text": "Great demo of the technology!"},
        content_type="application/json",
    )
    assert res.status_code == 201
    cmt_id = res.json()["id"]
    assert res.json()["state"] == "pending"

    # 2. Public view does NOT show pending comment
    res_pub = Client().get(f"/e/{event.id}/projects/{sub.id}.json")
    assert res_pub.status_code == 200
    assert len(res_pub.json().get("comments", [])) == 0

    # 3. Organizer sees comment in moderation queue
    res_queue = client.get(f"/e/{event.id}/comments.json", **bearer("admin"))
    assert res_queue.status_code == 200
    items = res_queue.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == cmt_id
    assert items[0]["state"] == "pending"

    # 4. Organizer approves comment
    res_app = client.post(f"/e/{event.id}/comments/{cmt_id}/approve.json", **bearer("admin"))
    assert res_app.status_code == 200

    # 5. Public view now displays approved comment
    res_pub2 = Client().get(f"/e/{event.id}/projects/{sub.id}.json")
    assert res_pub2.status_code == 200
    comments_list = res_pub2.json()["comments"]
    assert len(comments_list) == 1
    assert comments_list[0]["id"] == cmt_id
    assert "Great demo" in comments_list[0]["text"]


def test_comment_rejection(client, bearer):
    """S6: Rejected text is kept in the database and audited, but never shown publicly."""
    event, sub = _setup_event_with_project("evt_rej")
    author = Person.objects.create_user("spammer@example.org", password="pw")
    c_author = Client()
    c_author.force_login(author)

    res = c_author.post(
        f"/e/{event.id}/projects/{sub.id}/comments.json",
        {"text": "Buy crypto now at spam.example.com"},
        content_type="application/json",
    )
    assert res.status_code == 201
    cmt_id = res.json()["id"]

    # Organizer rejects comment
    res_rej = client.post(
        f"/e/{event.id}/comments/{cmt_id}/reject.json",
        {"reason": "Spam link"},
        content_type="application/json",
        **bearer("admin"),
    )
    assert res_rej.status_code == 200
    assert res_rej.json()["state"] == "rejected"

    # Verify kept in database
    cmt = ProjectComment.objects.get(id=cmt_id)
    assert cmt.state == "rejected"
    assert cmt.rejection_reason == "Spam link"

    # Not visible on public page
    res_pub = Client().get(f"/e/{event.id}/projects/{sub.id}.json")
    assert len(res_pub.json().get("comments", [])) == 0


def test_comment_escaping_and_csv_guard(client, bearer):
    """XSS escaping and CSV formula injection guard."""
    event, sub = _setup_event_with_project("evt_sec")
    author = Person.objects.create_user("tester.sec@example.org", password="pw")
    c_author = Client()
    c_author.force_login(author)

    # Text containing script tags and formula trigger
    payload_text = "=1+1<script>alert('pwn')</script>"
    res = c_author.post(
        f"/e/{event.id}/projects/{sub.id}/comments.json",
        {"text": payload_text},
        content_type="application/json",
    )
    cmt_id = res.json()["id"]

    # Approve
    client.post(f"/e/{event.id}/comments/{cmt_id}/approve.json", **bearer("admin"))

    # Check HTML output escapes script tags
    res_html = Client().get(f"/e/{event.id}/projects/{sub.id}")
    assert res_html.status_code == 200
    html_content = res_html.content.decode("utf-8")
    assert "<script>alert('pwn')</script>" not in html_content
    assert "&lt;script&gt;alert(&#x27;pwn&#x27;)&lt;/script&gt;" in html_content or "&lt;script&gt;" in html_content

    # Check CSV export guards leading '=' formula trigger
    res_csv = client.get(f"/e/{event.id}/comments.csv", **bearer("admin"))
    assert res_csv.status_code == 200
    csv_content = res_csv.content.decode("utf-8")
    # Formula guard prefixes with single quote
    assert "'=1+1" in csv_content
