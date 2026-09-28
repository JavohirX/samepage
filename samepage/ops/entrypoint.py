"""Migrate as the owner, seed in demo mode, then serve as the runtime role."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "samepage.settings")


def _wait_for_db(url: str) -> None:
    import time
    from urllib.parse import urlparse

    import psycopg

    parsed = urlparse(url)
    deadline = time.time() + 60
    last = "database did not accept connections within 60s"
    while time.time() < deadline:
        try:
            with psycopg.connect(url, connect_timeout=3) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return
        except Exception as exc:
            last = str(exc)
            time.sleep(1)
    raise SystemExit(f"database is not ready: {last}")


def _serve() -> None:
    bind = os.environ.get("BIND", "0.0.0.0:8000")
    if os.name == "nt" or os.environ.get("SAMEPAGE_SERVER") == "runserver":
        host, _, port = bind.rpartition(":")
        os.execv(sys.executable, [sys.executable, "manage.py", "runserver", f"{host or '127.0.0.1'}:{port}", "--noreload"])
    os.execvp(
        "gunicorn",
        ["gunicorn", "samepage.wsgi:application", "--bind", bind, "--workers", os.environ.get("WEB_CONCURRENCY", "2")],
    )


def main() -> None:
    if os.environ.get("SAMEPAGE_SERVE_ONLY") == "1":
        _serve()
    owner_url = os.environ.get("DB_OWNER_URL") or os.environ.get("DATABASE_URL")
    if not owner_url:
        raise SystemExit("Set DATABASE_URL or DB_OWNER_URL before starting Samepage.")
    _wait_for_db(owner_url)
    os.environ["DATABASE_URL"] = owner_url
    import django

    django.setup()
    from django.conf import settings
    from django.core.management import call_command

    call_command("migrate", interactive=False)
    if os.environ.get("DB_OWNER_URL"):
        from samepage.ops.roles import ensure_app_role

        ensure_app_role()
    if settings.DEMO_MODE:
        from samepage.services.seed import banner, seed

        fixture = os.environ.get("FIXTURE", str(Path(__file__).resolve().parents[2] / "fixtures.json"))
        try:
            seed(fixture)
        except Exception:
            # A second process can lose the race. The event existing is success.
            from samepage.apps.portal.models import Event

            if not Event.objects.filter(id="evt_01").exists():
                raise
        port = os.environ.get("PORT", "8080")
        print(banner(int(port)), flush=True)
    if os.environ.get("DB_OWNER_URL") and os.environ.get("SAMEPAGE_SKIP_ROLE_CHECK") != "1":
        from samepage.ops.roles import runtime_self_check
        from urllib.parse import urlparse, urlunparse

        app_password = os.environ.get("DB_APP_PASSWORD", "demo-app")
        parsed = urlparse(os.environ["DB_OWNER_URL"])
        app_url = urlunparse(parsed._replace(netloc=f"samepage_app:{app_password}@{parsed.hostname}:{parsed.port}"))
        runtime_self_check(app_url)
        os.environ["DATABASE_URL"] = app_url
        os.environ.pop("DB_OWNER_URL", None)
    _serve()


if __name__ == "__main__":
    main()
