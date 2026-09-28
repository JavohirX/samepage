"""Production mode refuses everything that is public in this repository."""

from __future__ import annotations

import pytest

from conftest import needs_db
from samepage.ops import preflight

GOOD_SECRET = "x" * 64


class FakeSettings:
    DEMO_MODE = False
    DEBUG = False
    DEMO_SECRET_KEY = "demo-secret-key-not-for-production-use-32b"
    DEFAULT_DB_PASSWORDS = {"", "demo-owner", "demo-app", "postgres", "password", "samepage"}

    def __init__(self, **overrides):
        self.SECRET_KEY = GOOD_SECRET
        self.ALLOWED_HOSTS = ["portal.example.org"]
        for key, value in overrides.items():
            setattr(self, key, value)


GOOD_ENV = {
    "DB_OWNER_URL": "postgres://owner:long-owner-password@db:5432/samepage",
    "DB_APP_PASSWORD": "long-app-password",
}


def test_clean_production_configuration_passes():
    assert preflight.config_problems(FakeSettings(), GOOD_ENV) == []


@pytest.mark.parametrize(
    "overrides, env, needle",
    [
        ({"SECRET_KEY": "demo-secret-key-not-for-production-use-32b"}, GOOD_ENV, "SECRET_KEY"),
        ({"SECRET_KEY": "short"}, GOOD_ENV, "SECRET_KEY"),
        ({"DEBUG": True}, GOOD_ENV, "DEBUG"),
        ({"ALLOWED_HOSTS": ["*"]}, GOOD_ENV, "ALLOWED_HOSTS"),
        ({}, {**GOOD_ENV, "DB_OWNER_URL": "postgres://owner:demo-owner@db:5432/samepage"}, "owner password"),
        ({}, {**GOOD_ENV, "DB_APP_PASSWORD": "demo-app"}, "DB_APP_PASSWORD"),
        ({}, {"DB_OWNER_URL": GOOD_ENV["DB_OWNER_URL"]}, "DB_APP_PASSWORD"),
        ({}, {"DATABASE_URL": "postgres://samepage_app:demo-app@db/samepage"}, "DATABASE_URL"),
    ],
)
def test_each_default_is_refused(overrides, env, needle):
    problems = preflight.config_problems(FakeSettings(**overrides), env)
    assert any(needle in problem for problem in problems), problems


def test_demo_mode_skips_the_refusals():
    settings = FakeSettings(SECRET_KEY="short")
    settings.DEMO_MODE = True
    preflight.refuse_unsafe_production(settings, check_data=False)


def test_refusal_exits_with_every_reason():
    with pytest.raises(SystemExit) as caught:
        preflight.refuse_unsafe_production(FakeSettings(SECRET_KEY="short", ALLOWED_HOSTS=["*"]), check_data=False)
    message = str(caught.value)
    assert message.startswith("SAMEPAGE_E_PRODUCTION")
    assert "SECRET_KEY" in message and "ALLOWED_HOSTS" in message


@needs_db
@pytest.mark.django_db
def test_a_demo_seeded_database_is_refused_in_production():
    problems = preflight.data_problems()
    assert any("demo bearer token" in problem for problem in problems)
    assert any("demo password" in problem for problem in problems)


@needs_db
@pytest.mark.django_db
def test_demo_tokens_are_401_in_production(client, bearer, production):
    response = client.get("/e/evt_01/scores.csv", **bearer("org"))
    assert response.status_code == 401
    assert "Demo tokens are refused" in response.content.decode("utf-8")
    assert client.get("/e/evt_01/judges/me/scores.json", **bearer("jdg08")).status_code == 401


@needs_db
@pytest.mark.django_db
def test_demo_tokens_work_in_demo_mode(client, bearer):
    assert client.get("/e/evt_01/scores.csv", **bearer("org")).status_code == 200


@needs_db
@pytest.mark.django_db
def test_demo_password_never_signs_in_in_production(client, production):
    response = client.post("/login", {"email": "organizer@example.org", "password": "samepage-demo"})
    assert response.status_code == 401
    assert "_auth_user_id" not in client.session


@needs_db
@pytest.mark.django_db
def test_demo_password_signs_in_in_demo_mode(client):
    response = client.post("/login", {"email": "organizer@example.org", "password": "samepage-demo"})
    assert response.status_code == 303
    assert client.session["_auth_user_id"] == "org_01"


@needs_db
@pytest.mark.django_db
def test_demo_sign_in_links_are_404_in_production(client, production):
    assert client.get("/demo/enter/org").status_code == 404
    assert client.post("/demo/enter/org").status_code == 404


def test_a_refused_production_boot_does_not_touch_the_app_role(monkeypatch, production):
    """The demo-data refusal runs before ensure_app_role, so samepage_app keeps its password."""
    import django
    import django.core.management as management

    from samepage.ops import entrypoint, roles

    steps = []
    monkeypatch.delenv("SAMEPAGE_SERVE_ONLY", raising=False)
    monkeypatch.setenv("DB_OWNER_URL", GOOD_ENV["DB_OWNER_URL"])
    # main() points DATABASE_URL at the owner; setenv first so it is restored afterwards.
    monkeypatch.setenv("DATABASE_URL", GOOD_ENV["DB_OWNER_URL"])
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(entrypoint, "_wait_for_db", lambda url: None)
    monkeypatch.setattr(entrypoint, "_serve", lambda: steps.append("serve"))
    monkeypatch.setattr(management, "call_command", lambda *args, **kwargs: steps.append(args[0]))
    monkeypatch.setattr(roles, "ensure_app_role", lambda: steps.append("ensure_app_role"))
    monkeypatch.setattr(preflight, "config_problems", lambda settings, environ=None: [])
    monkeypatch.setattr(preflight, "data_problems", lambda: ["1 demo bearer token(s) are still valid."])
    with pytest.raises(SystemExit) as caught:
        entrypoint.main()
    assert "demo bearer token" in str(caught.value)
    assert steps == ["migrate"]


def test_a_clean_production_boot_still_sets_up_the_app_role(monkeypatch, production):
    import django
    import django.core.management as management

    from samepage.ops import entrypoint, roles

    steps = []
    monkeypatch.delenv("SAMEPAGE_SERVE_ONLY", raising=False)
    monkeypatch.setenv("SAMEPAGE_SKIP_ROLE_CHECK", "1")
    monkeypatch.setenv("DB_OWNER_URL", GOOD_ENV["DB_OWNER_URL"])
    monkeypatch.setenv("DATABASE_URL", GOOD_ENV["DB_OWNER_URL"])
    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(entrypoint, "_wait_for_db", lambda url: None)
    monkeypatch.setattr(entrypoint, "_serve", lambda: steps.append("serve"))
    monkeypatch.setattr(management, "call_command", lambda *args, **kwargs: steps.append(args[0]))
    monkeypatch.setattr(roles, "ensure_app_role", lambda: steps.append("ensure_app_role"))
    monkeypatch.setattr(preflight, "config_problems", lambda settings, environ=None: [])
    monkeypatch.setattr(preflight, "data_problems", lambda: [])
    entrypoint.main()
    assert steps == ["migrate", "ensure_app_role", "serve"]
