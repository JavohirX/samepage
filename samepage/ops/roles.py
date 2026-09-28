"""Create samepage_app on every boot. Init scripts do not run again on a reused volume."""

from __future__ import annotations

import os

from django.db import connection


APP_ROLE = "samepage_app"


def ensure_app_role() -> None:
    password = os.environ.get("DB_APP_PASSWORD", "demo-app").replace("'", "''")
    statements = [
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}';
          ELSE
            ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{password}';
          END IF;
        END
        $$;
        """,
        f"GRANT CONNECT ON DATABASE {connection.settings_dict['NAME']} TO {APP_ROLE}",
        f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}",
        f"REVOKE UPDATE, DELETE ON TABLE score_rev FROM {APP_ROLE}",
        f"REVOKE UPDATE, DELETE ON TABLE audit_event FROM {APP_ROLE}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}",
    ]
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def runtime_self_check(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            superuser, bypass = cursor.fetchone()
            cursor.execute("SELECT has_table_privilege(current_user, 'score_rev', 'UPDATE')")
            can_update = cursor.fetchone()[0]
            cursor.execute("SELECT tableowner = current_user FROM pg_tables WHERE tablename = 'score_rev'")
            owns = cursor.fetchone()[0]
    if superuser or bypass or can_update or owns:
        raise SystemExit(
            "SAMEPAGE_E_DBROLE: runtime role can UPDATE score_rev or is too powerful; "
            "run the migrate phase with DB_OWNER_URL set."
        )
