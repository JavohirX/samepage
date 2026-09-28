"""Production refusals. The entrypoint calls `refuse_unsafe_production()` before it serves.

Demo mode is for a laptop: the sign-in links, the shared password and the bearer tokens
in .dogfood.toml are public. Production mode refuses to start while any of that, or a
default secret, is still in place. Each problem names its fix.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

MIN_SECRET_LENGTH = 50


def _password_of(url: str | None) -> str | None:
    if not url:
        return None
    return unquote(urlparse(url).password or "")


def config_problems(settings, environ=None) -> list[str]:
    """Checks that need no database."""
    environ = os.environ if environ is None else environ
    problems = []
    secret = settings.SECRET_KEY or ""
    if secret == settings.DEMO_SECRET_KEY or len(secret) < MIN_SECRET_LENGTH:
        problems.append(
            f"SECRET_KEY is the public demo key or shorter than {MIN_SECRET_LENGTH} characters. "
            "Set SECRET_KEY to a long random value."
        )
    if settings.DEBUG:
        problems.append("DEBUG is on. Unset SAMEPAGE_DEBUG.")
    if "*" in settings.ALLOWED_HOSTS:
        problems.append("ALLOWED_HOSTS contains '*'. List the host names the portal answers on.")
    owner = _password_of(environ.get("DB_OWNER_URL"))
    if owner is not None and owner in settings.DEFAULT_DB_PASSWORDS:
        problems.append("The database owner password is a default. Set DB_OWNER_PASSWORD (compose) or DB_OWNER_URL.")
    if environ.get("DB_OWNER_URL"):
        app_password = environ.get("DB_APP_PASSWORD", "demo-app")
        if app_password in settings.DEFAULT_DB_PASSWORDS:
            problems.append("DB_APP_PASSWORD is a default. Set it to a new value.")
    else:
        runtime = _password_of(environ.get("DATABASE_URL") or environ.get("DB_APP_URL"))
        if runtime is not None and runtime in settings.DEFAULT_DB_PASSWORDS:
            problems.append("The database password in DATABASE_URL is a default. Use a real one.")
    return problems


def data_problems() -> list[str]:
    """Checks that read the database: demo credentials left behind by a demo boot."""
    from django.contrib.auth.hashers import check_password
    from django.db.models import Q

    from samepage.apps.portal.models import ApiToken, Person
    from samepage.domain.tokens import DEMO_PASSWORD, PRINCIPALS

    problems = []
    demo_tokens = ApiToken.objects.filter(demo=True, revoked_at__isnull=True).count()
    if demo_tokens:
        problems.append(
            f"{demo_tokens} demo bearer token(s) are still valid. This database was seeded in demo mode; "
            "start production on a new database (docker compose down -v, or a new DB_OWNER_URL)."
        )
    ids = [spec["id"] for spec in PRINCIPALS.values()]
    emails = [spec["email"] for spec in PRINCIPALS.values()]
    for person in Person.objects.filter(Q(id__in=ids) | Q(email__in=emails), is_active=True):
        if person.has_usable_password() and check_password(DEMO_PASSWORD, person.password):
            problems.append(
                f"{person.email} still has the published demo password. Start production on a new database."
            )
            break
    return problems


def refuse_unsafe_production(settings, *, check_data: bool = True) -> None:
    if settings.DEMO_MODE:
        return
    problems = config_problems(settings)
    if check_data:
        problems += data_problems()
    if problems:
        lines = ["SAMEPAGE_E_PRODUCTION: refusing to start in production mode:"]
        lines += [f"  - {problem}" for problem in problems]
        raise SystemExit("\n".join(lines))
