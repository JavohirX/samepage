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
