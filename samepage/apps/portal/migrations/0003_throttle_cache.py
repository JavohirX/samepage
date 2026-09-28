"""The table Django's DatabaseCache reads (settings.CACHES["throttle"]).

Sign-in attempts are counted here, in Postgres, so every gunicorn worker sees one count
per client instead of one count each. The columns are the ones `createcachetable` makes;
a migration creates the table so no extra command has to run at boot, and the runtime
role gets DML on it through the GRANT ... ON ALL TABLES in ops/roles.py.
"""

from django.db import migrations

SQL = r"""
CREATE TABLE IF NOT EXISTS samepage_cache (
  cache_key varchar(255) NOT NULL PRIMARY KEY,
  value text NOT NULL,
  expires timestamp with time zone NOT NULL
);
CREATE INDEX IF NOT EXISTS samepage_cache_expires ON samepage_cache (expires);
"""

REVERSE = r"""
DROP TABLE IF EXISTS samepage_cache;
"""


class Migration(migrations.Migration):
    dependencies = [("portal", "0002_triggers")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
