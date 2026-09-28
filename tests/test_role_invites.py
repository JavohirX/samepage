"""Judge and organizer roles reach an existing account only when that account accepts them.

Anyone can sign up with any address, and judges' addresses are often public. If inviting an address
attached the role to whatever account already held it, a participant could pre-register a judge's
email and be handed the judge (or organizer) role. These tests drive that sequence over HTTP.
"""

from __future__ import annotations

import pytest
from django.test import Client

from conftest import needs_db
from samepage.apps.portal.models import AuditEvent, Event, Invite, JudgeTrack, Person, RoleGrant

pytestmark = [needs_db, pytest.mark.django_db]


def _signed_in(person: Person) -> Client:
    browser = Client()
    browser.force_login(person)
    return browser


def _squatter(email: str) -> tuple[Person, Client]:
    """A stranger who signed up with someone else's address and a password of their own."""
    browser = Client()
    response = browser.post("/signup", {"name": "Not the judge", "email": email, "password": "squatter password"})
    assert response.status_code == 303, response.content
    return Person.objects.get(email=email), browser


def _path(link: str) -> str:
    return "/" + link.split("/", 3)[3]


def test_a_pre_registered_judge_address_gets_no_judge_role(client, bearer):
    person, stranger = _squatter("famous.judge@example.net")
    assert stranger.get("/e/evt_02/judge/batches.json").status_code == 403
    added = client.post(
        "/e/evt_02/people.json",
        {"email": "famous.judge@example.net", "role": "judge", "tracks": ["trk_e2"]},
        content_type="application/json",
        **bearer("org"),
    )
    assert added.status_code == 201, added.content
    body = added.json()
    assert body["new_account"] is False and body["granted"] is False and body["status"] == "invited"
    assert body["password_link"] == "" and "/accept/ra_" in body["accept_link"]
    # The account holder never saw the link, so nothing is theirs.
    assert not RoleGrant.objects.filter(person=person, event_id="evt_02").exists()
    assert stranger.get("/e/evt_02/judge/batches.json").status_code == 403
    assert stranger.get("/e/evt_02/judges/me/scores.json").status_code == 403
    # Only the hash of the link is stored.
    token = body["accept_link"].rsplit("/", 1)[1]
    invite = Invite.objects.get(kind="role", person=person, event_id="evt_02")
    assert token not in invite.token_sha256 and invite.role == "judge" and invite.tracks == ["trk_e2"]
    # The organizer sees an unaccepted invitation, not a judge.
    rows = client.get("/e/evt_02/people.json", **bearer("org")).json()["items"]
    row = next(item for item in rows if item["email"] == "famous.judge@example.net")
    assert row["status"] == "invited" and row["invite_expires"] and row["assigned"] == ""
    assert "invited, not accepted" in client.get("/e/evt_02/settings", **bearer("org")).content.decode("utf-8")
    audit = AuditEvent.objects.filter(event_id="evt_02", action="people.invite_judge").last()
    assert audit.after["status"] == "invited" and audit.after["email"] == "famous.judge@example.net"


def test_a_pre_registered_organizer_address_gets_no_ledger(client, bearer):
    person, stranger = _squatter("famous.organizer@example.net")
    added = client.post(
        "/e/evt_01/people.json",
        {"email": "famous.organizer@example.net", "role": "organizer"},
        content_type="application/json",
        **bearer("org"),
    )
    assert added.status_code == 201 and added.json()["status"] == "invited"
    for path in ("/e/evt_01/scores.json", "/e/evt_01/audit.json", "/e/evt_01/settings.json", "/e/evt_01/progress.json"):
        assert stranger.get(path).status_code == 403, path
    assert stranger.post("/e/evt_01/publish.json").status_code == 403
    assert not RoleGrant.objects.filter(person=person, event_id="evt_01").exists()


def test_the_invited_account_accepts_and_only_then_holds_the_role(client, bearer):
    # A real existing account: someone who already judges another event with their own password.
    judge = Person.objects.create_user("returning.judge@example.org", password="returning password", name="Returning")
    added = client.post(
        "/e/evt_02/people.json",
        {"email": "returning.judge@example.org", "role": "judge", "tracks": ["trk_e2"]},
        content_type="application/json",
        **bearer("org"),
    ).json()
    path = _path(added["accept_link"])
    # Anyone may read what the link offers; accepting needs the invited account.
    preview = Client().get(path + ".json")
    assert preview.status_code == 200 and preview.json()["role"] == "judge"
    assert preview.json()["email"] == "returning.judge@example.org" and preview.json()["is_invitee"] is False
    anonymous = Client().post(path + ".json")
    assert anonymous.status_code == 401 and "Location" not in anonymous
    other = _signed_in(Person.objects.create_user("someone.else@example.org", password="another password"))
    refused = other.post(path + ".json")
    assert refused.status_code == 403 and "returning.judge@example.org" in refused.json()["detail"]
    assert not RoleGrant.objects.filter(person=judge, event_id="evt_02").exists()
    browser = _signed_in(judge)
    assert browser.get(path + ".json").json()["is_invitee"] is True
    accepted = browser.post(path + ".json")
    assert accepted.status_code == 200, accepted.content
    assert accepted.json() == {"event": "evt_02", "role": "judge", "tracks": ["trk_e2"], "granted": True}
    assert RoleGrant.objects.filter(person=judge, event_id="evt_02", role="judge").exists()
    assert list(JudgeTrack.objects.filter(person=judge, event_id="evt_02").values_list("track_id", flat=True)) == ["trk_e2"]
    assert browser.get("/e/evt_02/judge/batches.json").status_code == 200
    assert AuditEvent.objects.filter(event_id="evt_02", action="people.accept_judge", actor=judge.id).exists()
    # One use.
    assert browser.post(path + ".json").status_code == 404
    rows = client.get("/e/evt_02/people.json", **bearer("org")).json()["items"]
    assert [row["status"] for row in rows if row["email"] == "returning.judge@example.org"] == ["active"]


def test_the_acceptance_page_and_form_in_a_browser(bearer, client):
    judge = Person.objects.create_user("html.judge@example.org", password="html judge password")
    link = client.post(
        "/e/evt_02/people.json", {"email": "html.judge@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    ).json()["accept_link"]
    path = _path(link)
    page = Client().get(path).content.decode("utf-8")
    assert "Sign in as html.judge@example.org" in page and f"/login?next={path}" in page
    wrong = _signed_in(Person.objects.create_user("wrong.person@example.org", password="wrong person pw"))
    assert "Only html.judge@example.org can accept" in wrong.get(path).content.decode("utf-8")
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(judge)
    form = browser.get(path)
    assert "Accept as html.judge@example.org" in form.content.decode("utf-8")
    assert browser.post(path).status_code == 403  # no CSRF token
    done = browser.post(path, {"csrfmiddlewaretoken": form.cookies["csrftoken"].value})
    assert done.status_code == 303 and done["Location"] == "/account"
    assert "evt_02" in browser.get("/account").content.decode("utf-8")


def test_a_new_invitation_replaces_the_unaccepted_one(client, bearer):
    Person.objects.create_user("twice@example.org", password="twice password")
    first = client.post(
        "/e/evt_02/people.json", {"email": "twice@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    ).json()["accept_link"]
    second = client.post(
        "/e/evt_02/people.json", {"email": "twice@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    ).json()["accept_link"]
    assert first != second
    browser = _signed_in(Person.objects.get(email="twice@example.org"))
    assert browser.post(_path(first) + ".json").status_code == 404
    assert browser.post(_path(second) + ".json").status_code == 200


def test_a_judge_invitation_cannot_be_accepted_after_publish(client, bearer):
    person = Person.objects.create_user("late.judge@example.org", password="late judge password")
    link = client.post(
        "/e/evt_02/people.json", {"email": "late.judge@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    ).json()["accept_link"]
    Event.objects.filter(id="evt_02").update(state="published")
    assert _signed_in(person).post(_path(link) + ".json").status_code == 409
    assert not RoleGrant.objects.filter(person=person, event_id="evt_02").exists()


def test_a_new_address_still_gets_its_role_with_the_password_link(client, bearer):
    added = client.post(
        "/e/evt_02/people.json", {"email": "brand.new@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    ).json()
    assert added["status"] == "active" and added["granted"] is True and added["accept_link"] == ""
    assert "/password/pw_" in added["password_link"]
    # Nobody can sign in to the new account except through that link, and sign-up for the address is refused.
    assert Client().post("/signup", {"name": "X", "email": "brand.new@example.org", "password": "squatter password"}).status_code == 409
