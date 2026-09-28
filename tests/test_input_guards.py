"""Input that used to reach Postgres or the date parser and fail there as a 500 is 422 with the field named."""

from __future__ import annotations

import pytest
from django.test import Client

from conftest import needs_db
from samepage.apps.portal.models import Event, Person, Team

pytestmark = [needs_db, pytest.mark.django_db]

NUL = "\x00"


def _signed_in(person: Person) -> Client:
    browser = Client()
    browser.force_login(person)
    return browser


# --- NUL characters: 422 with the field named, never a 500 ------------------------------------

JSON_WRITES = [
    ("admin", "post", "/e.json", {"name": f"a{NUL}b", "submissions_close": "2031-01-01T00:00:00Z", "tracks": ["A"]}, "name"),
    ("org", "post", "/e/evt_02/settings.json", {"description": f"x{NUL}y"}, "description"),
    ("org", "patch", "/e/evt_02/settings.json", {"description": f"x{NUL}y"}, "description"),
    ("org", "post", "/e/evt_01/criteria.json", {"criteria": [{"label": f"Imp{NUL}act", "weight": 1}]}, "criteria.label"),
    ("org", "post", "/e/evt_02/people.json", {"email": f"a{NUL}@example.net", "role": "judge"}, "email"),
    ("org", "post", "/e/evt_01/assignments.json", {"judge": f"jdg_0{NUL}1", "project": "prj_01"}, "judge"),
    ("priya1", "post", "/e/evt_01/projects.json", {"title": f"a{NUL}b"}, "title"),
    ("priya1", "patch", "/e/evt_01/projects/prj_01.json", {"title": f"a{NUL}b"}, "title"),
    ("jdg08", "post", "/e/evt_01/judge/assignments/prj_01/scores.json", {"comment": f"a{NUL}"}, "comment"),
    ("org", "post", "/e/evt_01/duplicates/dup_01/confirm.json", {"resolution": f"merge{NUL}"}, "resolution"),
]


@pytest.mark.parametrize("slug, method, path, body, field", JSON_WRITES, ids=[row[2] + ":" + row[1] for row in JSON_WRITES])
def test_a_nul_in_a_json_body_is_422(client, bearer, slug, method, path, body, field):
    response = getattr(client, method)(path, body, content_type="application/json", **bearer(slug))
    assert response.status_code == 422, response.content
    assert response.json()["errors"] == {field: "contains a NUL character"}


def test_a_nul_in_a_team_name_is_422_and_creates_nothing():
    browser = _signed_in(Person.objects.create_user("nul.team@example.org", password="nul team password"))
    response = browser.post("/e/evt_02/teams.json", {"name": f"a{NUL}b"}, content_type="application/json")
    assert response.status_code == 422 and response.json()["errors"] == {"name": "contains a NUL character"}
    assert not Team.objects.filter(event_id="evt_02", name__startswith="a").exists()


@pytest.mark.parametrize(
    "path, body, field",
    [
        ("/login", {"email": f"a{NUL}@example.net", "password": "whatever password"}, "email"),
        ("/login", {"email": "organizer@example.org", "password": f"pw{NUL}"}, "password"),
        ("/signup", {"name": f"A{NUL}", "email": "nul.name@example.org", "password": "long enough pw"}, "name"),
        ("/signup", {"name": "A", "email": f"nul{NUL}@example.org", "password": "long enough pw"}, "email"),
        ("/signup", {"name": "A", "email": "nul.pw@example.org", "password": f"long enough{NUL}pw"}, "password"),
    ],
)
def test_anonymous_sign_in_and_sign_up_with_a_nul_are_422(path, body, field):
    response = Client().post(path, body)
    assert response.status_code == 422, response.content
    assert "contains a NUL character" in response.content.decode("utf-8")
    assert not Person.objects.filter(email__startswith="nul").exists()


def test_a_nul_in_a_query_string_is_422(client, bearer):
    public = client.get("/e/evt_01/projects.json?q=a%00b")
    assert public.status_code == 422 and public.json()["errors"] == {"q": "contains a NUL character"}
    assert client.get("/e/evt_01/projects.csv?tags=x%00").status_code == 422
    assert client.get("/e/evt_01/scores.json?judge=jdg%0001", **bearer("org")).status_code == 422
    # The policy answers first: an anonymous caller of a private page still gets 401.
    assert client.get("/e/evt_01/scores.json?judge=jdg%0001").status_code == 401


# --- impossible dates ----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["2026-02-30T10:00:00Z", "2026-13-01T00:00:00Z", "2026-10-01T25:00:00Z"])
def test_an_impossible_date_is_422_on_create_and_settings(client, bearer, value):
    created = client.post(
        "/e.json", {"name": "Bad date", "submissions_close": value, "tracks": ["A"]}, content_type="application/json", **bearer("admin")
    )
    assert created.status_code == 422, created.content
    assert "submissions_close" in created.json()["errors"]
    assert not Event.objects.filter(name="Bad date").exists()
    before = Event.objects.get(id="evt_02").submissions_close
    updated = client.post("/e/evt_02/settings.json", {"submissions_close": value}, content_type="application/json", **bearer("org"))
    assert updated.status_code == 422 and "submissions_close" in updated.json()["errors"]
    assert Event.objects.get(id="evt_02").submissions_close == before
    judging = client.post("/e/evt_02/settings.json", {"judging_ends": value}, content_type="application/json", **bearer("org"))
    assert judging.status_code == 422 and "judging_ends" in judging.json()["errors"]
