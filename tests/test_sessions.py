"""Sign-in is a cookie write, so it needs a CSRF token; a GET never signs anyone in."""

from __future__ import annotations

import pytest
from django.test import Client

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def _csrf(client: Client, path: str) -> str:
    client.get(path)
    return client.cookies["csrftoken"].value


def test_demo_link_get_shows_a_button_and_does_not_sign_in():
    client = Client(enforce_csrf_checks=True)
    response = client.get("/demo/enter/org")
    assert response.status_code == 200
    assert b'action="/demo/enter/org"' in response.content
    assert "_auth_user_id" not in client.session
    assert client.get("/e/evt_01/progress.json").status_code == 401


def test_demo_sign_in_post_needs_the_csrf_token():
    client = Client(enforce_csrf_checks=True)
    assert client.post("/demo/enter/org").status_code == 403
    token = _csrf(client, "/demo/enter/org")
    response = client.post("/demo/enter/org", {"csrfmiddlewaretoken": token})
    assert response.status_code == 303
    assert response["Location"] == "/e/evt_01/progress"
    assert client.get("/e/evt_01/progress.json").status_code == 200


def test_login_without_csrf_token_is_refused():
    client = Client(enforce_csrf_checks=True)
    response = client.post("/login", {"email": "organizer@example.org", "password": "samepage-demo"})
    assert response.status_code == 403
    assert "_auth_user_id" not in client.session


def test_login_with_csrf_token_signs_in():
    client = Client(enforce_csrf_checks=True)
    token = _csrf(client, "/login")
    response = client.post(
        "/login", {"email": "organizer@example.org", "password": "samepage-demo", "csrfmiddlewaretoken": token}
    )
    assert response.status_code == 303


def test_login_is_throttled_but_get_routes_are_not(client):
    statuses = [
        client.post("/login", {"email": "organizer@example.org", "password": "wrong"}).status_code for _ in range(11)
    ]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert all(client.get("/e/evt_01/projects").status_code == 200 for _ in range(30))


def test_login_count_is_shared_by_every_worker(client):
    """The count sits in Postgres, so a worker with empty memory still sees the earlier attempts."""
    from django.core.cache import caches
    from django.db import connection

    for _ in range(10):
        client.post("/login", {"email": "organizer@example.org", "password": "wrong"})
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM samepage_cache WHERE cache_key LIKE %s", ["%throttle_login_%"])
        assert cursor.fetchone()[0] == 1
    # What a second gunicorn worker has in memory: nothing.
    caches["default"].clear()
    response = client.post("/login", {"email": "organizer@example.org", "password": "wrong"})
    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0


@pytest.mark.parametrize("suffix", [".json", ".csv"])
@pytest.mark.parametrize("who", [None, "org", "priya1"])
def test_login_has_no_api_twin(client, bearer, suffix, who):
    headers = bearer(who) if who else {}
    for method in (client.get, client.post):
        response = method(f"/login{suffix}", **headers)
        assert response.status_code == 404
        assert "Location" not in response
        assert response["Content-Type"].startswith("application/problem+json")


def test_login_next_cannot_leave_the_site(client):
    response = client.post(
        "/login", {"email": "organizer@example.org", "password": "samepage-demo", "next": "https://evil.example/"}
    )
    assert response["Location"] == "/"


def test_the_front_door_asks_a_stranger_for_a_role_and_a_password(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b'action="/login"' in response.content and b'name="role"' in response.content
    assert "public" not in response.get("Cache-Control", "")  # the page carries a CSRF token
    assert client.get("/e").status_code == 200  # the plain event list stays public


@pytest.mark.parametrize(
    ("email", "role", "landing"),
    [
        ("admin@example.org", "admin", "/"),
        ("organizer@example.org", "organizer", "/e/evt_01/progress"),
        ("marek.nowak@example.org", "judge", "/e/evt_01/judge/batches"),
        ("priya1@example.org", "participant", "/e/evt_01/teams/tm_01"),
    ],
)
def test_signing_in_as_a_role_lands_on_that_roles_panel(client, email, role, landing):
    response = client.post("/login", {"email": email, "password": "samepage-demo", "role": role})
    assert response.status_code == 303
    assert response["Location"] == landing


def test_signing_in_as_a_role_the_account_does_not_hold_is_refused(client):
    response = client.post("/login", {"email": "marek.nowak@example.org", "password": "samepage-demo", "role": "admin"})
    assert response.status_code == 403
    assert b"It can sign in as: judge" in response.content
    assert "_auth_user_id" not in client.session


def test_a_next_link_wins_over_the_role_landing(client):
    response = client.post(
        "/login", {"email": "organizer@example.org", "password": "samepage-demo", "role": "organizer", "next": "/account"}
    )
    assert response["Location"] == "/account"
