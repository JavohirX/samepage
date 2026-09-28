# Operations

## Boot

`python -m samepage.ops.entrypoint` is the container command. In order it:

1. refuses to start in production mode if the configuration has a public default (see Production), before touching the database;
2. waits for Postgres and migrates as the owner (`DB_OWNER_URL`);
3. production mode: refuses to start if demo tokens or demo passwords are in the database. This runs before the role step, so a refused boot leaves `samepage_app` and its password as they were (the migrations have run);
4. creates or updates the `samepage_app` role and its grants (every boot, because init scripts do not re-run on a reused volume);
5. demo mode: seeds `fixtures.json` once, fits the results snapshot, prints the demo tokens;
6. checks that `samepage_app` cannot update `score_rev` and owns nothing, drops `DB_OWNER_URL` from the environment and execs gunicorn as that role.

```
docker compose up --wait
```

starts `app` and `db`. Postgres is not published. The web port is `${PORT:-8080}` on `${SAMEPAGE_BIND_ADDR:-127.0.0.1}`. The app container runs as uid 10001 with a read-only root filesystem, no capabilities and a tmpfs `/tmp`. Its healthcheck (`python -m samepage.ops.healthcheck`) sends the first `ALLOWED_HOSTS` entry as the Host header, so it also works in production mode.

Profiles, not started by a plain `up`:

- `ops`: `backup` writes `backups/latest/db.dump` and a media tar. `restore` loads them.
- `test`: pytest inside the test image, against a `test_samepage` database on the compose Postgres.
- `oracle`: statsmodels re-derives the ranking from `http://app:8000` (README, check 3).

`/healthz` answers 200 while the process runs, whatever the database state. `/readyz` answers 503 `application/problem+json` when Postgres cannot be reached within the 5 second connect timeout.

Logs go to stdout: one gunicorn access line per request with `cid=<correlation id>`, and for every 500 a traceback plus a line with the same correlation id the error page shows as "Reference".

## Production

`SAMEPAGE_MODE` is `demo` or `production`. Outside compose it defaults to `production`; any other value stops the process.

Set a `SECRET_KEY` of at least 50 characters, `DB_OWNER_PASSWORD` and `DB_APP_PASSWORD` (URL-safe characters; they go into a connection URL), `ALLOWED_HOSTS`, and `PUBLIC_URL`. When `PUBLIC_URL` is https, session and CSRF cookies are marked Secure. Put TLS on a reverse proxy. Behind exactly one proxy that sets `X-Forwarded-For`, set `SAMEPAGE_NUM_PROXIES=1` so the sign-in throttle (10 POSTs a minute per client, shared by sign-in, sign-up and set-password) keys on the real client. The throttle counts in a Postgres table (`samepage_cache`), so the limit holds across all gunicorn workers.

The process refuses to start, and names each fix, when any of these hold (`samepage/ops/preflight.py`):

- `SECRET_KEY` is the demo key or shorter than 50 characters;
- `SAMEPAGE_DEBUG=1`;
- `ALLOWED_HOSTS` contains `*`;
- the owner or runtime database password is a known default (`demo-owner`, `demo-app`, `postgres`, `password`, `samepage`, empty);
- the database holds an unrevoked demo bearer token, or a demo account whose password is still `samepage-demo`.

A database first booted in demo mode therefore never serves in production mode. Start production on a new volume (`docker compose down -v`) or a new database. At request time, too, production mode answers 401 to a demo token, never accepts the demo password, and 404s `/demo/enter/*`.

```
SAMEPAGE_MODE=production SECRET_KEY=... DB_OWNER_PASSWORD=... DB_APP_PASSWORD=... \
  ALLOWED_HOSTS=portal.example.org PUBLIC_URL=https://portal.example.org docker compose up --wait
```

A production database starts empty. Make the first admin, then do everything else in the portal:

```
docker compose exec -e SAMEPAGE_ADMIN_PASSWORD app python manage.py samepage_admin --email you@example.org --name "You"
```

The password comes from `SAMEPAGE_ADMIN_PASSWORD` (or a prompt with a terminal), never from the command line, must be 10 characters or more and cannot be the demo password. A one-off `manage.py` command in the app container connects with `DB_OWNER_URL`, which compose sets; the served process keeps using `samepage_app`. Running it again for an existing email promotes that account and sets the password.

Then sign in at `/login` and:

1. **New event** on the home page: windows (UTC), tracks, prizes, rubric, custom questions, team size. It starts as a draft; **Move to open** on its settings page.
2. Invite judges and co-organizers by email on the settings page. A new person gets a one-time set-password link on the next page (valid 14 days). An address that already has an account gets a one-time acceptance link instead (valid 14 days): the role is theirs once they open it signed in and accept. Nothing is emailed; send it yourself.
3. Participants sign up at `/signup`, start a team on the event page and invite their teammates with the team's link.
4. After the deadline: **Move to closed**, **Move to judging**, then **Issue batches** on the progress page. Watch Progress; top up or abandon batches as judges drop out; reopen a finalized score from the assignments page if a judge asks.
5. Confirm any duplicate decision, then **Publish results**. The ranking is frozen from then on.

`tools/lifecycle_check.py` does all of that over HTTP against a running portal; CI runs it in production mode on a fresh volume (receipts/production-lifecycle.txt). A forgotten password: `docker compose exec app python manage.py changepassword <email>`.

Upgrade is `git pull`, `docker compose build`, `docker compose up --wait`. Migrations are forward only. Roll back by restoring the backup taken before the upgrade, then checking out the previous tree.

## Backup

```
docker compose --profile ops run --rm backup
docker compose --profile ops run --rm restore
```

Take a backup before every upgrade. `backups/` holds password hashes and token digests; it is in `.gitignore` and `.dockerignore`.

## Local, without Docker

Python 3.12 (the exact-fraction formatting needs it) and a running Postgres. The entrypoint does the same steps as in the container; on Windows it serves with `runserver` instead of gunicorn.

```
pip install -r requirements.txt
set SAMEPAGE_MODE=demo
set DB_OWNER_URL=postgres://postgres:postgres@127.0.0.1:5432/samepage
set BIND=127.0.0.1:8080
python -m samepage.ops.entrypoint
```

## Windows

`python`, not `python3`. `curl.exe`, not `curl`. Line endings are LF (`.gitattributes`). The entrypoint is Python, not a shell script, so a CRLF checkout does not break boot.

## If someone forks this

1. Run production mode on a new database until it boots clean.
2. `manage.py samepage_admin`, sign in, create the event (see Production).
3. Point people at Download CSV on any organizer list, and at `results.json` after publish.

The first gaps: no email delivery (links are handed on by hand), no SSO, no self-service password reset, no webhooks, no signed records, and read isolation lives in application code.
