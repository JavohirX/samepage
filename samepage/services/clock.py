"""One clock: the database's now()."""

from __future__ import annotations

from django.db import connection


def db_now():
    with connection.cursor() as cursor:
        cursor.execute("SELECT now()")
        return cursor.fetchone()[0]
