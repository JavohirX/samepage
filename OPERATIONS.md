# Operations

## Boot

`python -m samepage.ops.entrypoint` is the container command. In order it:

1. in production mode, refuses to start if the configuration has a public default (see [Production](#production)), before touching the database;
2. waits up to 60 seconds for Postgres and migrates as the owner (`DB_OWNER_URL`, or `DATABASE_URL` when there is no owner URL);
3. in production mode, refuses to start if demo tokens or demo passwords are in the database. This runs before the role step, so a refused boot leaves `samepage_app` and its password as they were (the migrations have run);
4. when `DB_OWNER_URL` is set, creates or updates the `samepage_app` role and its grants (every boot, because init scripts do not re-run on a reused volume);
5. in demo mode, seeds `fixtures.json` once (skipped when evt_01 exists), fits the results snapshot and prints the demo sign-in links, the password and the four bearer headers; in production mode it prints `samepage production mode: preflight passed`;
6. when `DB_OWNER_URL` is set, connects as `samepage_app` and refuses to start if that role is a superuser, can bypass row security, can update `score_rev` or owns it; then drops `DB_OWNER_URL` from the environment and serves as that role: gunicorn with `WEB_CONCURRENCY` workers (2 by default), or Django's `runserver` on Windows.

```
docker compose up --wait
```

starts `app` and `db`. Postgres is not published. The web port is `${PORT:-8080}` on `${SAMEPAGE_BIND_ADDR:-127.0.0.1}`; if you change `PORT`, change `base_url` in `.dogfood.toml` to match. The app container runs as uid 10001 with a read-only root filesystem, no capabilities, `no-new-privileges`, an init process and a tmpfs `/tmp`. Its healthcheck (`python -m samepage.ops.healthcheck`) sends the first `ALLOWED_HOSTS` entry as the Host header, so it also works in production mode.

Profiles, not started by a plain `up`:

- `ops`: `backup` and `restore` (see [Backup](#backup)).
- `test`: pytest inside the test image, against a `test_samepage` database on the compose Postgres.
- `oracle`: statsmodels re-derives the ranking from `http://app:8000` (README, check 3).

`/healthz` answers 200 while the process runs, whatever the database state. `/readyz` answers 503 `application/problem+json` when Postgres cannot be reached within the 5 second connect timeout.

Logs go to stdout: one gunicorn access line per request with `cid=<correlation id>`, and for every 500 a traceback plus a line with the same correlation id that the error page shows as "Reference".

## Configuration

| Variable | Meaning |
|---|---|
| `SAMEPAGE_MODE` | `demo` or `production`. Compose defaults to `demo`; everywhere else the default is `production`. Any other value stops the process. |
| `SECRET_KEY` | Django's secret. Production needs 50 characters or more, and not the public demo key. |
| `DB_OWNER_PASSWORD`, `DB_APP_PASSWORD` | Compose: the owner's and the runtime role's database passwords (URL-safe characters; they go into a connection URL). |
| `DB_OWNER_URL` | The owner's URL, for migrations and the role handoff. Compose builds it from `DB_OWNER_PASSWORD`. |
| `DATABASE_URL` | Without `DB_OWNER_URL`: the one database URL the app uses, with no role handoff. |
| `ALLOWED_HOSTS` | Comma-separated host names the portal answers on. Default `localhost,127.0.0.1,app`. |
| `PUBLIC_URL` | The address people use; one-time links are built on it. When it is `https://…` in production mode, session and CSRF cookies are marked Secure. |
| `PORT`, `SAMEPAGE_BIND_ADDR` | Compose: the host port (8080) and the address it is published on (127.0.0.1). |
| `SAMEPAGE_NUM_PROXIES` | 0 (default): the sign-in throttle keys on the TCP peer. Set 1 behind exactly one proxy that sets `X-Forwarded-For`. |
| `SAMEPAGE_LOGIN_RATE` | The shared sign-in, sign-up and set-password throttle. Default `10/min`. |
| `SAMEPAGE_ENGINE_BOOT_BUDGET_S` | Seconds a results fit may take before the fallback ranking is used instead. Default 30; 0 switches the model off. |
| `WEB_CONCURRENCY` | gunicorn workers. Default 2. |
| `SAMEPAGE_DEBUG` | `1` turns Django's DEBUG on, in demo mode only. Production mode ignores it. |

Three switches exist for tests and emergencies and are not for normal use: `SAMEPAGE_SERVE_ONLY=1` skips migrations and the role steps (it still runs the production refusals), `SAMEPAGE_SKIP_ROLE_CHECK=1` skips the runtime role self-check in step 6, and `SAMEPAGE_FAST_HASH=1` stores new passwords with a fast MD5 hasher. Production mode does not refuse any of them; never set `SAMEPAGE_FAST_HASH` on a real instance.

## Production

Set `SAMEPAGE_MODE=production`, a `SECRET_KEY` of at least 50 characters, `DB_OWNER_PASSWORD` and `DB_APP_PASSWORD`, `ALLOWED_HOSTS` and `PUBLIC_URL`.

The process refuses to start, and names each fix, when any of these hold (`samepage/ops/preflight.py`):

- `SECRET_KEY` is the demo key or shorter than 50 characters;
- `ALLOWED_HOSTS` contains `*`;
- the owner or runtime database password is a known default (`demo-owner`, `demo-app`, `postgres`, `password`, `samepage`, empty);
- the database holds an unrevoked demo bearer token, or a demo account whose password is still `samepage-demo`.

A database first booted in demo mode therefore never serves in production mode. Start production on a new volume (`docker compose down -v`) or a new database. At request time, too, production mode answers 401 to a demo token, never accepts the demo password, and answers 404 on `/demo/enter/*`.

```
SAMEPAGE_MODE=production SECRET_KEY=... DB_OWNER_PASSWORD=... DB_APP_PASSWORD=... \
  ALLOWED_HOSTS=portal.example.org PUBLIC_URL=https://portal.example.org docker compose up --wait
```

Read [TLS and proxies](#tls-and-proxies) before putting it behind HTTPS.

A production database starts empty. Make the first admin, then do everything else in the portal:

```
docker compose exec -e SAMEPAGE_ADMIN_PASSWORD app python manage.py samepage_admin --email you@example.org --name "You"
```

The password comes from `SAMEPAGE_ADMIN_PASSWORD` (or a prompt when there is a terminal), never from the command line. It must be 10 characters or more and cannot be the demo password. A one-off `manage.py` command in the app container connects with `DB_OWNER_URL`, which Compose sets; the served process keeps using `samepage_app`. Running the command again for an existing email makes that account an admin and sets the password.

Then sign in at `/login` and:

1. **New event** on the home page: windows (UTC), tracks, prizes, rubric, custom questions, team size. It starts as a draft, visible only to its organizers and admins; **Move to open** on its settings page.
2. Invite judges and co-organizers by email on the settings page. A new person gets a one-time set-password link on the next page (valid 14 days). An address that already has an account in use gets a one-time acceptance link instead (valid 14 days): the role is theirs once they open it signed in and accept. Nothing is emailed; send the link yourself.
3. Participants sign up at `/signup`, start a team on the event page and invite their teammates with the team's link.
4. After the deadline: **Move to closed**, **Move to judging**, then **Issue batches** on the progress page. Watch Progress; top up or abandon batches as judges drop out; reopen a finalized score from the assignments page if a judge asks.
5. Confirm any duplicate decision, then **Publish results**. The ranking is frozen from then on.

`tools/lifecycle_check.py` does all of that over HTTP against a running portal (`SAMEPAGE_ADMIN_PASSWORD=... python tools/lifecycle_check.py --base <PUBLIC_URL> --admin-email you@example.org`); CI runs it in production mode on a fresh volume ([receipts/production-lifecycle.txt](receipts/production-lifecycle.txt)). A forgotten password: `docker compose exec app python manage.py changepassword <email>`.

### TLS and proxies

The app speaks plain HTTP; put TLS on a reverse proxy in front of the published port, and set `SAMEPAGE_NUM_PROXIES=1` behind exactly one proxy that sets `X-Forwarded-For`, so the sign-in throttle keys on the real client.

Known gap: there is no setting yet for a proxy that terminates TLS (`SECURE_PROXY_SSL_HEADER`, `CSRF_TRUSTED_ORIGINS`). Django then sees `http` while the browser sends `Origin: https://portal.example.org`, and every browser form post, sign-in included, fails the CSRF check with 403. Until that is added, a proxy that terminates TLS has to rewrite the `Origin` header to the `http://` form, or the portal has to be served over plain HTTP on a trusted network. CI does not test a TLS deployment.

### Upgrade

`git pull`, `docker compose build`, `docker compose up --wait`. Take a backup first. Migrations are forward only; to go back, restore the backup taken before the upgrade on the previous tree. CI tests backup and restore, not a downgrade.

## Backup

```
docker compose --profile ops run --rm backup
docker compose --profile ops run --rm restore
```

`backup` writes `backups/latest/db.dump` (`pg_dump -Fc`, which includes the uploaded images, stored in Postgres) and `backups/latest/media.tar` (the media volume), replacing the previous `latest`. `restore` runs `pg_restore --clean --if-exists` into the running database, so everything written after the backup is gone, and then unpacks the tar. `backups/` holds password hashes and token digests; it is in `.gitignore` and `.dockerignore`.

CI proves the round trip on the demo stack with `python tools/verify.py backup` ([receipts/backup-restore.txt](receipts/backup-restore.txt)): back up, merge the Dry Harbour duplicate, restore, and `scores.csv`, the audit log and its chain, and the duplicate decision must equal what they were at the backup.

## Local, without Docker

Python 3.12 (the exact-fraction formatting needs it) and a running Postgres (16 in CI; 18 also works). The owner role in the URL must be allowed to create roles, because the entrypoint creates `samepage_app`; a local superuser such as `postgres` is simplest. The entrypoint does the same steps as in the container. On Windows it serves with `runserver` instead of gunicorn.

Linux or macOS:

```
pip install -r requirements.txt
createdb -U postgres samepage
SAMEPAGE_MODE=demo DB_OWNER_URL=postgres://postgres:postgres@127.0.0.1:5432/samepage \
  BIND=127.0.0.1:8080 python -m samepage.ops.entrypoint
```

Windows (cmd):

```
pip install -r requirements.txt
createdb -U postgres samepage
set SAMEPAGE_MODE=demo
set DB_OWNER_URL=postgres://postgres:postgres@127.0.0.1:5432/samepage
set BIND=127.0.0.1:8080
python -m samepage.ops.entrypoint
```

Then `python run.py .dogfood.toml` works unchanged, and so do `python tools/oracle_statsmodels.py --toml .dogfood.toml` (after `pip install -r requirements-oracle.txt`) and `tools/lifecycle_check.py`. `BIND` is the address the server listens on; `PORT` only changes the address printed in the boot banner. Outside the image nothing has run `collectstatic`, so WhiteNoise serves the static files from the source tree and logs a warning that `staticfiles/` is missing; it is harmless.

## Windows

`python`, not `python3`. `curl.exe`, not `curl`. Line endings are LF (`.gitattributes`). The entrypoint is Python, not a shell script, so a CRLF checkout does not break boot.

`runserver` listens on the one address in `BIND`, 127.0.0.1 above. Windows tries `::1` first for `localhost`, so every request to `http://localhost:8080` waits for that attempt to fail before it reaches the portal, about 2 seconds each. `run.py .dogfood.toml` still passes, only slower. For a quick native run, use a copy of `.dogfood.toml` with `base_url = "http://127.0.0.1:8080"`. Keep the committed file as it is, because it serves the compose path.

## If someone forks this

1. Run production mode on a new database until it boots clean.
2. `manage.py samepage_admin`, sign in, create the event (see [Production](#production)).
3. Point people at Download CSV on any organizer list, and at `results.json` after publish.

The first gaps: TLS behind a proxy (above), no email delivery (links are handed on by hand), no SSO, no self-service password reset, no API tokens outside demo mode, and read isolation lives in application code.
