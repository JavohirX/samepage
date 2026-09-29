"""The T1 lifecycle over HTTP: accounts, events, teams by invite link, drafts, edits, the deadline, the gallery.

Every flow is driven through the same URLs a browser and an API client use, and the refusals are
checked in the answer (status and body) and in the database (nothing written).
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import (
    AuditEvent,
    Criterion,
    Event,
    Invite,
    Person,
    PrizeCategory,
    RoleGrant,
    Submission,
    SubmissionMedia,
    Team,
    TeamMember,
    Track,
)
from samepage.services.clock import db_now

pytestmark = [needs_db, pytest.mark.django_db]

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _iso(delta: timedelta) -> str:
    return (timezone.now() + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _person(email: str, name: str = "", password: str = "correct horse battery") -> Person:
    return Person.objects.create_user(email, password=password, name=name or email.split("@")[0])


def _as(person: Person) -> Client:
    client = Client()
    client.force_login(person)
    return client


@pytest.fixture
def event(client, bearer):
    """An open event created through the API by the demo admin, closing tomorrow."""
    body = {
        "name": "Autumn Hack",
        "description": "Two tracks.",
        "submissions_close": _iso(timedelta(days=1)),
        "judging_ends": _iso(timedelta(days=3)),
        "tracks": ["Tools", "Climate"],
        "prizes": ["Grand prize", "Best newcomer"],
        "criteria": [{"label": "Functionality", "weight": 2}, {"label": "Quality", "weight": 1}],
        "custom_questions": [
            {"label": "License", "kind": "choice", "choices": ["MIT", "Apache-2.0"], "required": True},
            {"label": "What did you learn?"},
        ],
        "max_team_size": 2,
    }
    response = client.post("/e.json", body, content_type="application/json", **bearer("admin"))
    assert response.status_code == 201, response.content
    event_id = response.json()["id"]
    opened = client.post(f"/e/{event_id}/state.json", {"state": "open"}, content_type="application/json", **bearer("admin"))
    assert opened.status_code == 200, opened.content
    return Event.objects.get(id=event_id)


# --- accounts --------------------------------------------------------------------------------


def test_signup_hashes_the_password_signs_in_and_needs_csrf():
    browser = Client(enforce_csrf_checks=True)
    page = browser.get("/signup")
    assert page.status_code == 200
    token = page.cookies["csrftoken"].value
    refused = browser.post("/signup", {"name": "Ana", "email": "ana@example.org", "password": "long enough pw"})
    assert refused.status_code == 403
    assert not Person.objects.filter(email="ana@example.org").exists()
    done = browser.post(
        "/signup",
        {"name": "Ana", "email": "Ana@Example.org", "password": "long enough pw", "next": "/account", "csrfmiddlewaretoken": token},
    )
    assert done.status_code == 303 and done["Location"] == "/account"
    person = Person.objects.get(email="ana@example.org")
    assert person.password != "long enough pw" and person.check_password("long enough pw")
    assert browser.get("/account.json").json()["email"] == "ana@example.org"


@pytest.mark.parametrize(
    "body, field",
    [
        ({"name": "A", "email": "not-an-email", "password": "long enough pw"}, "email"),
        ({"name": "A", "email": "a@example.org", "password": "short"}, "password"),
        ({"name": "A", "email": "a@example.org", "password": "samepage-demo"}, "password"),
        ({"name": "", "email": "a@example.org", "password": "long enough pw"}, "name"),
    ],
)
def test_signup_refuses_bad_input_with_422(client, body, field):
    response = client.post("/signup", body)
    assert response.status_code == 422
    assert not Person.objects.filter(email=body["email"]).exists()


def test_signup_with_a_taken_email_is_409(client):
    response = client.post("/signup", {"name": "X", "email": "organizer@example.org", "password": "long enough pw"})
    assert response.status_code == 409


def test_login_accepts_a_real_account_and_refuses_a_wrong_password(client):
    _person("real@example.org", password="a real password")
    assert client.post("/login", {"email": "real@example.org", "password": "wrong password"}).status_code == 401
    assert client.post("/login", {"email": "real@example.org", "password": "a real password"}).status_code == 303
    assert client.get("/account.json").json()["email"] == "real@example.org"


def test_change_password_needs_the_current_one(client):
    person = _person("change@example.org", password="first password")
    browser = _as(person)
    assert browser.post("/account.json", {"current_password": "nope", "password": "second password"}, content_type="application/json").status_code == 422
    assert browser.post(
        "/account.json", {"current_password": "first password", "password": "second password"}, content_type="application/json"
    ).status_code == 200
    person.refresh_from_db()
    assert person.check_password("second password")


def test_admin_command_bootstraps_a_production_admin(monkeypatch, production):
    from django.core.management import call_command

    monkeypatch.setenv("SAMEPAGE_ADMIN_PASSWORD", "a long admin password")
    call_command("samepage_admin", email="Boss@Example.org", name="Boss")
    boss = Person.objects.get(email="boss@example.org")
    assert boss.is_admin and boss.check_password("a long admin password")
    client = Client()
    assert client.post("/login", {"email": "boss@example.org", "password": "a long admin password"}).status_code == 303
    created = client.post(
        "/e.json",
        {"name": "Prod event", "submissions_close": _iso(timedelta(days=7)), "tracks": "Main"},
        content_type="application/json",
    )
    assert created.status_code == 201


@pytest.mark.parametrize(
    "email, password, message",
    [
        ("ops@example.org", "samepage-demo", "password: That password is published in this repository. Choose another."),
        ("ops@example.org", "short", "password: "),
        ("not-an-email", "a long admin password", "email: "),
    ],
)
def test_admin_command_refusals_are_plain_sentences(monkeypatch, production, email, password, message):
    from django.core.management import call_command
    from django.core.management.base import CommandError

    monkeypatch.setenv("SAMEPAGE_ADMIN_PASSWORD", password)
    with pytest.raises(CommandError) as refused:
        call_command("samepage_admin", email=email, name="Ops")
    text = str(refused.value)
    assert text.startswith(message)
    assert "ErrorDetail" not in text and "{" not in text and "[" not in text
    assert not Person.objects.filter(email__iexact=email).exists()


def test_manage_py_createsuperuser_path_makes_a_global_admin():
    admin = Person.objects.create_superuser("root@example.org", password="another long one")
    assert admin.is_admin and admin.id.startswith("per_")


# --- events ----------------------------------------------------------------------------------


def test_admin_creates_an_event_with_tracks_prizes_rubric_and_questions(client, bearer, event):
    detail = client.get(f"/e/{event.id}.json").json()
    assert detail["state"] == "open"
    assert sorted(track["name"] for track in detail["tracks"]) == ["Climate", "Tools"]
    assert sorted(prize["name"] for prize in detail["prizes"]) == ["Best newcomer", "Grand prize"]
    assert [(row["key"], row["weight"]) for row in detail["criteria"]] == [("functionality", "2"), ("quality", "1")]
    assert detail["custom_questions"][0]["choices"] == ["MIT", "Apache-2.0"]
    assert detail["max_team_size"] == 2
    assert RoleGrant.objects.filter(event=event, person_id="adm_01", role="organizer").exists()
    actions = list(AuditEvent.objects.filter(event=event).values_list("action", flat=True))
    assert actions[:2] == ["event.create", "event.state"]


def test_event_create_form_redirects_to_its_settings(client, django_user_model):
    browser = _as(Person.objects.get(id="adm_01"))
    response = browser.post(
        "/e",
        {"name": "Form event", "submissions_close": "2031-01-01T12:00", "tracks": "One\nTwo", "prizes": "Best"},
    )
    assert response.status_code == 303
    event = Event.objects.get(name="Form event")
    assert response["Location"] == f"/e/{event.id}/settings"
    assert event.submissions_close.isoformat().startswith("2031-01-01T12:00:00")
    assert Track.objects.filter(event=event).count() == 2 and PrizeCategory.objects.filter(event=event).count() == 1
    assert browser.get(f"/e/{event.id}/settings").status_code == 200


@pytest.mark.parametrize(
    "body, field",
    [
        ({"name": "X", "tracks": "A"}, "submissions_close"),
        ({"name": "X", "tracks": "A", "submissions_close": "tomorrow"}, "submissions_close"),
        ({"name": "X", "submissions_close": "2031-01-01T00:00:00Z"}, "tracks"),
        ({"name": "X", "tracks": "A", "submissions_close": "2031-01-01T00:00:00Z", "starts_at": "2031-02-01T00:00:00Z"}, "starts_at"),
        ({"name": "X", "tracks": "A", "submissions_close": "2031-01-01T00:00:00Z", "criteria": [{"label": "F", "weight": 0}]}, "weight"),
        ({"name": "X", "tracks": "A", "submissions_close": "2031-01-01T00:00:00Z", "max_team_size": 50}, "max_team_size"),
    ],
)
def test_bad_event_bodies_are_422_and_create_nothing(client, bearer, body, field):
    before = Event.objects.count()
    response = client.post("/e.json", body, content_type="application/json", **bearer("admin"))
    assert response.status_code == 422, response.content
    assert field in response.json()["detail"]
    assert Event.objects.count() == before


@pytest.mark.parametrize("slug, status", [("org", 403), ("jdg08", 403), ("priya1", 403)])
def test_only_global_admins_create_events(client, bearer, slug, status):
    body = {"name": "Nope", "submissions_close": "2031-01-01T00:00:00Z", "tracks": "A"}
    assert client.post("/e.json", body, content_type="application/json", **bearer(slug)).status_code == status
    assert client.post("/e.json", body, content_type="application/json").status_code == 401


def test_organizer_edits_settings_adds_tracks_and_moves_state(client, bearer, event):
    url = f"/e/{event.id}/settings.json"
    response = client.post(
        url,
        {"name": "Autumn Hack 2", "add_tracks": ["Health"], "add_prizes": "People's choice", "blind_judging": True},
        content_type="application/json",
        **bearer("admin"),
    )
    assert response.status_code == 200, response.content
    event.refresh_from_db()
    assert event.name == "Autumn Hack 2" and event.blind_judging
    assert Track.objects.filter(event=event, name="Health").exists()
    # Closing before the deadline is refused; publishing goes through the results page only.
    assert client.post(f"/e/{event.id}/state.json", {"state": "closed"}, content_type="application/json", **bearer("admin")).status_code == 409
    assert client.post(f"/e/{event.id}/state.json", {"state": "published"}, content_type="application/json", **bearer("admin")).status_code == 409
    assert client.post(f"/e/{event.id}/state.json", {"state": "draft"}, content_type="application/json", **bearer("admin")).status_code == 409
    assert client.post(url, {"name": "Hijack"}, content_type="application/json", **bearer("priya1")).status_code == 403
    assert client.get(f"/e/{event.id}/settings.json", **bearer("jdg08")).status_code == 403


def test_draft_events_are_hidden_from_the_public_list(client, bearer):
    client.post(
        "/e.json",
        {"name": "Secret draft", "submissions_close": "2031-01-01T00:00:00Z", "tracks": "A"},
        content_type="application/json",
        **bearer("admin"),
    )
    public = [row["name"] for row in client.get("/e.json").json()["items"]]
    assert "Secret draft" not in public
    staff = [row["name"] for row in client.get("/e.json", **bearer("admin")).json()["items"]]
    assert "Secret draft" in staff


# --- teams -----------------------------------------------------------------------------------


def test_team_formation_by_invite_link(client, event):
    lead = _person("lead@example.org")
    mate = _person("mate@example.org")
    extra = _person("extra@example.org")
    lead_browser = _as(lead)
    created = lead_browser.post(f"/e/{event.id}/teams.json", {"name": "Night Owls"}, content_type="application/json")
    assert created.status_code == 201, created.content
    team_id = created.json()["id"]
    assert RoleGrant.objects.filter(person=lead, event=event, role="participant").exists()

    invite = lead_browser.post(f"/e/{event.id}/teams/{team_id}/invites.json", {"max_uses": 5}, content_type="application/json")
    assert invite.status_code == 201
    path = invite.json()["path"]
    assert path.startswith("/join/tj_")
    stored = Invite.objects.get(id=invite.json()["id"])
    assert path.rsplit("/", 1)[1] not in stored.token_sha256  # only the hash is stored

    assert Client().get(path).status_code == 200  # anyone with the link sees which team
    assert Client().post(path + ".json").status_code == 401  # joining needs an account
    joined = _as(mate).post(path + ".json")
    assert joined.status_code == 200, joined.content
    assert TeamMember.objects.filter(team_id=team_id).count() == 2
    # max_team_size is 2 for this event.
    assert _as(extra).post(path + ".json").status_code == 409
    team = lead_browser.get(f"/e/{event.id}/teams/{team_id}.json").json()
    assert sorted(member["email"] for member in team["members"]) == ["lead@example.org", "mate@example.org"]
    # Outsiders and judges cannot read the team page; organizers can.
    assert _as(extra).get(f"/e/{event.id}/teams/{team_id}.json").status_code == 403
    assert client.get(f"/e/{event.id}/teams/{team_id}.json").status_code == 401
    staff = _as(Person.objects.get(id="adm_01"))
    assert staff.get(f"/e/{event.id}/teams/{team_id}.json").status_code == 200
    assert staff.get(f"/e/{event.id}/teams.csv").status_code == 200
    assert lead_browser.get(f"/e/{event.id}/teams.json").status_code == 403
    actions = set(AuditEvent.objects.filter(event=event).values_list("action", flat=True))
    assert {"team.create", "invite.create", "team.join"} <= actions


def test_an_invite_link_can_be_revoked_and_used_up(event):
    lead = _as(_person("l2@example.org"))
    team_id = lead.post(f"/e/{event.id}/teams.json", {"name": "Revokers"}, content_type="application/json").json()["id"]
    first = lead.post(f"/e/{event.id}/teams/{team_id}/invites.json", {"max_uses": 1}, content_type="application/json").json()
    lead.post(f"/e/{event.id}/teams/{team_id}/invites/{first['id']}/revoke.json")
    assert Client().get(first["path"]).status_code == 404
    second = lead.post(f"/e/{event.id}/teams/{team_id}/invites.json", {"max_uses": 1}, content_type="application/json").json()
    assert _as(_person("u1@example.org")).post(second["path"] + ".json").status_code == 200
    assert _as(_person("u2@example.org")).post(second["path"] + ".json").status_code == 404


def test_judges_and_organizers_cannot_join_teams_and_one_team_each(client, bearer, event):
    lead = _as(_person("l3@example.org"))
    team_id = lead.post(f"/e/{event.id}/teams.json", {"name": "Solo"}, content_type="application/json").json()["id"]
    path = lead.post(f"/e/{event.id}/teams/{team_id}/invites.json", {}, content_type="application/json").json()["path"]
    judge = _person("judge3@example.org")
    RoleGrant.objects.create(person=judge, event=event, role="judge")
    # The policy refuses before the service looks: a judge's role on the event is not "participant or visitor".
    assert _as(judge).post(path + ".json").status_code == 403
    assert _as(judge).post(f"/e/{event.id}/teams.json", {"name": "Judges"}, content_type="application/json").status_code == 403
    assert lead.post(f"/e/{event.id}/teams.json", {"name": "Second"}, content_type="application/json").status_code == 409
    assert client.post(f"/e/{event.id}/teams.json", {"name": "Anon"}, content_type="application/json").status_code == 401


def test_leaving_and_organizer_removal(event):
    lead_person = _person("l4@example.org")
    lead = _as(lead_person)
    team_id = lead.post(f"/e/{event.id}/teams.json", {"name": "Leavers"}, content_type="application/json").json()["id"]
    path = lead.post(f"/e/{event.id}/teams/{team_id}/invites.json", {}, content_type="application/json").json()["path"]
    mate = _person("m4@example.org")
    _as(mate).post(path + ".json")
    staff = _as(Person.objects.get(id="adm_01"))
    assert lead.post(f"/e/{event.id}/teams/{team_id}/members/{mate.id}/remove.json").status_code == 403
    assert staff.post(f"/e/{event.id}/teams/{team_id}/members/{mate.id}/remove.json").status_code == 200
    assert not TeamMember.objects.filter(person=mate).exists()
    assert not RoleGrant.objects.filter(person=mate, event=event, role="participant").exists()
    assert lead.post(f"/e/{event.id}/teams/{team_id}/leave.json").status_code == 200
    assert not Team.objects.filter(id=team_id).exists()  # empty and without a submission


def test_teams_are_fixed_after_the_deadline(event):
    lead = _as(_person("l5@example.org"))
    team_id = lead.post(f"/e/{event.id}/teams.json", {"name": "Late"}, content_type="application/json").json()["id"]
    path = lead.post(f"/e/{event.id}/teams/{team_id}/invites.json", {}, content_type="application/json").json()["path"]
    Event.objects.filter(id=event.id).update(submissions_close=db_now() - timedelta(seconds=1))
    assert _as(_person("late@example.org")).post(path + ".json").status_code == 409
    assert lead.post(f"/e/{event.id}/teams/{team_id}/leave.json").status_code == 409


# --- submissions -----------------------------------------------------------------------------


@pytest.fixture
def team(event):
    lead = _person("builder@example.org", name="Builder")
    browser = _as(lead)
    team_id = browser.post(f"/e/{event.id}/teams.json", {"name": "Builders"}, content_type="application/json").json()["id"]
    return {"id": team_id, "browser": browser, "person": lead}


def test_draft_edit_submit_lifecycle(client, event, team):
    browser = team["browser"]
    tools = Track.objects.get(event=event, name="Tools").id
    created = browser.post(
        f"/e/{event.id}/projects.json",
        {
            "title": "Quiet Hours",
            "tagline": "Focus timer",
            "description": "Long text",
            "repo_url": "https://example.org/repo",
            "live_url": "https://example.org/live",
            "video_url": "https://example.org/video",
            "tech_tags": "python django",
            "track": tools,
            "custom_answers": {"what_did_you_learn": "Deadlines are real"},
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    project = created.json()["id"]
    assert created.json()["state"] == "draft"
    # A draft is the team's: not in the public gallery, 403 to others, visible to the team and staff.
    assert project not in [row["id"] for row in client.get(f"/e/{event.id}/projects.json").json()["items"]]
    assert client.get(f"/e/{event.id}/projects/{project}.json").status_code == 403
    assert _as(_person("other@example.org")).get(f"/e/{event.id}/projects/{project}.json").status_code == 403
    assert browser.get(f"/e/{event.id}/projects/{project}.json").status_code == 200
    staff = _as(Person.objects.get(id="adm_01"))
    assert project in [row["id"] for row in staff.get(f"/e/{event.id}/projects.json?state=all").json()["items"]]

    # Edit: JSON PATCH and the HTML form both work until the deadline.
    patched = browser.patch(f"/e/{event.id}/projects/{project}.json", {"tagline": "Deep focus"}, content_type="application/json")
    assert patched.status_code == 200 and patched.json()["version"] == 2
    form = browser.post(f"/e/{event.id}/projects/{project}", {"title": "Quiet Hours", "tech_tags": "python rust", "track": tools})
    assert form.status_code == 303
    row = Submission.objects.get(id=project)
    assert row.tagline == "Deep focus" and row.tech_tags == ["python", "rust"]

    # The required choice question must be answered before submitting, with one of its choices.
    assert browser.post(f"/e/{event.id}/projects/{project}/submit.json").status_code == 422
    assert browser.patch(f"/e/{event.id}/projects/{project}.json", {"q_license": "GPL"}, content_type="application/json").status_code == 422
    assert browser.patch(f"/e/{event.id}/projects/{project}.json", {"q_license": "MIT"}, content_type="application/json").status_code == 200
    submitted = browser.post(f"/e/{event.id}/projects/{project}/submit.json")
    assert submitted.status_code == 200 and submitted.json()["state"] == "submitted"
    public = client.get(f"/e/{event.id}/projects/{project}.json").json()
    assert public["item"]["state"] == "submitted"
    assert {row["key"]: row["answer"] for row in public["answers"]} == {"license": "MIT", "what_did_you_learn": "Deadlines are real"}
    assert "member_emails" in public["html_omitted"]
    actions = list(AuditEvent.objects.filter(event=event, object_ref=project).values_list("action", flat=True))
    assert actions[0] == "submission.create" and "submission.submit" in actions


def test_only_the_team_edits_and_one_submission_per_team(client, bearer, event, team):
    project = team["browser"].post(f"/e/{event.id}/projects.json", {"title": "Mine"}, content_type="application/json").json()["id"]
    outsider = _as(_person("outsider@example.org"))
    assert outsider.patch(f"/e/{event.id}/projects/{project}.json", {"title": "Theirs"}, content_type="application/json").status_code == 403
    assert client.patch(f"/e/{event.id}/projects/{project}.json", {"title": "Anon"}, content_type="application/json").status_code == 401
    assert team["browser"].post(f"/e/{event.id}/projects.json", {"title": "Second"}, content_type="application/json").status_code == 409
    assert outsider.post(f"/e/{event.id}/projects.json", {"title": "No team"}, content_type="application/json").status_code == 403


def test_the_deadline_stops_edits_in_the_service_and_in_the_database(event, team):
    browser = team["browser"]
    project = browser.post(
        f"/e/{event.id}/projects.json", {"title": "Before", "submit": True, "q_license": "MIT"}, content_type="application/json"
    ).json()["id"]
    Event.objects.filter(id=event.id).update(submissions_close=db_now() - timedelta(seconds=1))
    response = browser.patch(f"/e/{event.id}/projects/{project}.json", {"title": "After"}, content_type="application/json")
    assert response.status_code == 409
    assert "submissions closed at" in response.json()["detail"]
    assert Submission.objects.get(id=project).title == "Before"
    assert browser.post(f"/e/{event.id}/projects.json", {"title": "Late"}, content_type="application/json").status_code == 409
    # The trigger refuses a content edit that skips the service.
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            Submission.objects.filter(id=project).update(title="Sneaky")
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            SubmissionMedia.objects.create(
                submission_id=project, kind="gallery", position=1, sha256="0" * 64, content_type="image/png", data=PNG, size=len(PNG)
            )


def test_images_are_sniffed_stored_in_postgres_and_served_with_the_project(client, event, team):
    from django.core.files.uploadedfile import SimpleUploadedFile

    browser = team["browser"]
    project = browser.post(f"/e/{event.id}/projects.json", {"title": "Pictures"}, content_type="application/json").json()["id"]
    upload = browser.post(
        f"/e/{event.id}/projects/{project}/media.json",
        {"kind": "thumbnail", "file": SimpleUploadedFile("t.png", PNG, content_type="image/png")},
    )
    assert upload.status_code == 201, upload.content
    url = upload.json()["url"]
    assert Submission.objects.get(id=project).thumbnail == url
    fake = browser.post(
        f"/e/{event.id}/projects/{project}/media.json",
        {"kind": "gallery", "file": SimpleUploadedFile("x.png", b"<svg onload=alert(1)>", content_type="image/png")},
    )
    assert fake.status_code == 422
    # While a draft, only the team sees the image.
    assert client.get(url).status_code == 403
    image = browser.get(url)
    assert image.status_code == 200 and image["Content-Type"] == "image/png" and image.content == PNG
    browser.patch(f"/e/{event.id}/projects/{project}.json", {"q_license": "MIT"}, content_type="application/json")
    assert browser.post(f"/e/{event.id}/projects/{project}/submit.json").status_code == 200
    assert client.get(url).status_code == 200
    media_id = upload.json()["id"]
    assert browser.post(f"/e/{event.id}/projects/{project}/media/{media_id}/delete.json").status_code == 200
    assert Submission.objects.get(id=project).thumbnail == ""


def test_withdraw_by_the_team_hides_the_project(client, event, team):
    browser = team["browser"]
    project = browser.post(
        f"/e/{event.id}/projects.json", {"title": "Gone", "submit": True, "q_license": "MIT"}, content_type="application/json"
    ).json()["id"]
    assert project in [row["id"] for row in client.get(f"/e/{event.id}/projects.json").json()["items"]]
    assert browser.post(f"/e/{event.id}/projects/{project}/withdraw.json", {"reason": "changed our minds"}, content_type="application/json").status_code == 200
    assert project not in [row["id"] for row in client.get(f"/e/{event.id}/projects.json").json()["items"]]


def test_html_forms_render_for_the_team(event, team):
    browser = team["browser"]
    assert browser.get(f"/e/{event.id}/projects/new").status_code == 200
    project = browser.post(f"/e/{event.id}/projects", {"title": "Via form", "q_license": "MIT", "submit": "true"})
    assert project.status_code == 303
    project_id = project["Location"].rsplit("/", 1)[1]
    assert Submission.objects.get(id=project_id).state == "submitted"
    assert browser.get(f"/e/{event.id}/projects/{project_id}/edit").status_code == 200
    assert browser.get(f"/e/{event.id}/teams/{team['id']}").status_code == 200
    assert browser.get(f"/e/{event.id}").status_code == 200
    assert _as(_person("nobody@example.org")).get(f"/e/{event.id}/projects/{project_id}/edit").status_code == 403


# --- gallery ---------------------------------------------------------------------------------


def test_gallery_page_one_has_the_fixture_titles_in_html_json_and_csv(client):
    html = client.get("/e/evt_01/projects").content.decode("utf-8")
    for title in ("Glass Signal", "Small Meadow", "Deep Compass"):
        assert title in html
    first = [row["title"] for row in client.get("/e/evt_01/projects.json").json()["items"][:3]]
    assert first == ["Glass Signal", "Small Meadow", "Deep Compass"]
    rows = list(csv.DictReader(io.StringIO(client.get("/e/evt_01/projects.csv").content.decode("utf-8"))))
    assert [row["title"] for row in rows[:3]] == first


def test_gallery_search_and_multi_track_and_tag_filters(client, event):
    tools = Track.objects.get(event=event, name="Tools").id
    climate = Track.objects.get(event=event, name="Climate").id
    for index, (track, tags) in enumerate([(tools, "python django"), (climate, "python rust"), (tools, "go")]):
        browser = _as(_person(f"g{index}@example.org"))
        team_id = browser.post(f"/e/{event.id}/teams.json", {"name": f"G{index}"}, content_type="application/json").json()["id"]
        browser.post(
            f"/e/{event.id}/projects.json",
            {"title": f"Entry {index}", "track": track, "tech_tags": tags, "q_license": "MIT", "submit": True},
            content_type="application/json",
        )
    def titles(query):
        return sorted(row["title"] for row in client.get(f"/e/{event.id}/projects.json?{query}").json()["items"])

    assert titles("") == ["Entry 0", "Entry 1", "Entry 2"]
    assert titles(f"track={tools}") == ["Entry 0", "Entry 2"]
    assert titles(f"track={tools}&track={climate}") == ["Entry 0", "Entry 1", "Entry 2"]
    assert titles("tag=python") == ["Entry 0", "Entry 1"]
    assert titles("tag=python&tag=rust") == ["Entry 1"]
    assert titles("q=rust") == ["Entry 1"]
    assert titles("q=entry+2") == ["Entry 2"]
    csv_rows = list(csv.DictReader(io.StringIO(client.get(f"/e/{event.id}/projects.csv?tag=python").content.decode("utf-8"))))
    assert sorted(row["title"] for row in csv_rows) == ["Entry 0", "Entry 1"]
    assert "Entry 1" in client.get(f"/e/{event.id}/projects?track={climate}").content.decode("utf-8")


def test_an_operator_resets_a_forgotten_password_with_changepassword(monkeypatch):
    from django.contrib.auth.management.commands import changepassword
    from django.core.management import call_command

    person = _person("forgot@example.org", password="old password here")
    monkeypatch.setattr(changepassword.getpass, "getpass", lambda prompt="": "brand new password")
    call_command("changepassword", "forgot@example.org")
    person.refresh_from_db()
    assert person.check_password("brand new password")
