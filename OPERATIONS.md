# Operations

## Boot

`python -m samepage.ops.entrypoint` waits for Postgres, migrates as the owner, creates or updates `samepage_app`, seeds the fixture when `SAMEPAGE_MODE=demo`, fits the snapshot, checks the runtime role, drops `DB_OWNER_URL` from the environment, and execs gunicorn.

```
docker compose up --wait
```

starts two services: `app` and `db`. Postgres is not published. The web port is `${PORT:-8080}`.

Profiles, not started by a plain `up`:

- `ops` — `backup` writes `backups/latest/db.dump` and a media tar. `restore` loads them.
- `test` — pytest against the owner URL.
- `oracle` — statsmodels, talking to `http://app:8000`.

The database healthcheck uses `pg_isready -h 127.0.0.1`, so it does not report healthy during initdb's socket-only server.

## Production

Set `SAMEPAGE_MODE=production`, a long `SECRET_KEY`, real database passwords, `ALLOWED_HOSTS`, `PUBLIC_URL`, and `TRUSTED_PROXIES` if a proxy sets `X-Forwarded-For`. Put TLS on the proxy. The process refuses to boot if demo tokens remain, if DEBUG is on, if the secret or database password is a default, or if hosts are `*`.

Password reset without SMTP, once a mailbox exists in the database: set a token out of band and hand the person the link. There is no outbound mailer.

Upgrade is `git pull`, `docker compose build`, `docker compose up --wait`. Migrations are forward only. Roll back by restoring the backup taken before the upgrade, then checking out the previous tree. Do not expect a reverse migration.

## Backup

```
docker compose --profile ops run --rm backup
docker compose --profile ops run --rm restore
```

Take a backup before every upgrade.

## Local, without Docker

Postgres must already be running. Create a database and point at it:

```
set DATABASE_URL=postgres://postgres:postgres@127.0.0.1:5432/samepage
python manage.py migrate
python -c "import django; django.setup(); from samepage.services.seed import seed; seed('fixtures.json')"
python manage.py runserver 127.0.0.1:8080
```

Set `SAMEPAGE_FAST_HASH=1` only for tests. The demo seed hashes one shared password.

## Windows

`python`, not `python3`. `curl.exe`, not `curl`. Line endings are LF (`.gitattributes`). The entrypoint is Python, not a shell script, so a CRLF checkout does not break boot.

## If someone forks this

1. Run production mode until it boots clean, then import real registrations.
2. Invite judges by the accounts you create. The fixture's demo links will be gone.
3. Point people at Download CSV on any organizer list, and at `results.json` after publish.

The first gaps: no SSO, no webhooks, no signed records, and read isolation lives in application code.
