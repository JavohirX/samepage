"""HTTP and database tests run against Postgres, because the rules under test live there too
(deadline and append-only triggers). pytest-django creates test_<name> from DATABASE_URL,
migrates it (triggers included) and the seed below loads fixtures.json once per session.
Each test runs in a transaction that is rolled back.

Local run: DATABASE_URL=postgres://owner:pw@127.0.0.1:5432/samepage python -m pytest
Compose: docker compose --profile test run --rm test
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

needs_db = pytest.mark.skipif(
    not (os.environ.get("DATABASE_URL") or os.environ.get("DB_APP_URL")),
    reason="set DATABASE_URL to a Postgres the tests may create a database on",
)


def pytest_configure(config):
    from django.conf import settings

    # One seed hashes the demo password; tests sign in many times. Speed only, not behaviour.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    if not (os.environ.get("DATABASE_URL") or os.environ.get("DB_APP_URL")):
        return
    from django.conf import settings

    with django_db_blocker.unblock():
        demo = settings.DEMO_MODE
        settings.DEMO_MODE = True
        try:
            from samepage.services.seed import seed

            seed(str(ROOT / "fixtures.json"))
        finally:
            settings.DEMO_MODE = demo


@pytest.fixture(autouse=True)
def demo_mode(settings):
    """Tests run in demo mode unless they switch to production themselves."""
    settings.DEMO_MODE = True
    settings.MODE = "demo"
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def production(settings):
    settings.DEMO_MODE = False
    settings.MODE = "production"
    return settings


@pytest.fixture
def bearer():
    """bearer("org") -> the Authorization header the checker sends for that demo principal."""
    from samepage.domain.tokens import demo_token

    def header(slug: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {demo_token(slug)}"}

    return header
