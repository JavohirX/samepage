# Architecture

Two containers: `app` (Django 5.2 and Django REST Framework under gunicorn, two workers by default, `WEB_CONCURRENCY`) and `db` (Postgres 16). Pages are rendered on the server with Pico CSS; the only script is `console.js`, for autosave and keyboard scoring in the judge console. Every request runs in one database transaction (`ATOMIC_REQUESTS`). There is no queue, no cache server and no second service: the throttle counter, the audit chain and the results snapshots all live in Postgres.

## One URL, three formats

One URL is one resource. The suffix picks the format:

- `/e/evt_01/scores` is HTML.
- `/e/evt_01/scores.json` is JSON. The top-level value is an object.
- `/e/evt_01/scores.csv` is RFC 4180 CSV.

Without a suffix the `Accept` header decides: none, `*/*` or `text/html` gives HTML (so `run.py`, which sends no `Accept`, gets HTML), `application/json` gives JSON, `text/csv` gives CSV, anything else HTML. `?format=` is ignored (`URL_FORMAT_OVERRIDE` is off). A suffix a route does not offer is 404. DRF's own content negotiation is replaced by one that never answers 406, because the view chooses the format.

All three formats go through one view class (`SamepageView`, `samepage/core/views.py`), one policy check, one service call and one list of dicts; only the renderer differs (`samepage/core/renderers.py`). Suffixed patterns are registered first, with slug converters, so `prj_01.json` is not captured as an id. `/login`, `/signup`, `/password/<token>` and the HTML forms have no suffixed twin. `/judges/me/scores.json/x.csv` matches no route, so it is 404 rather than a cached private body.

## Request order

1. Bearer authentication, if an `Authorization` header is present. A bad bearer is 401 and never falls back to a cookie.
2. Session authentication otherwise. Cookie writes need a CSRF token; bearer writes do not.
3. The policy check (`SamepageView.initial` calls `services/access.require`, which asks `core/policy.allows`), before the target id is loaded. A view declares `action` (what reading the URL needs) and, where a write needs more, `write_action`. A judge opening another judge's scores is 403 even when that judge does not exist. A draft event is then 404 to everyone but its organizers and admins, the same answer as an id that was never created.
4. A NUL character in the query string is 422 (Postgres text cannot hold one).
5. The service builds the rows. Object-level rules (a member of this team, an assignment of this judge, a draft of this team) are checked there, before the row is returned or written.
6. The renderer.

Errors are plain Django responses: problem+json (RFC 9457) for `.json` and `.csv` URLs and for JSON clients, a problem page for HTML, and the sign-in form with status 401 and `WWW-Authenticate: Bearer` for an HTML 401. A DRF response on a `.csv` route would be re-rendered as CSV and become a 500, which fails `run.py`. A 404 or 500 raised before any view runs (an unknown URL, a database that is down) still follows the URL's suffix. A 500 body carries a reference id and no stack; the stack goes to the log with the same id.

Writes use the same views. A form post gets a 303 to the page that shows the result, except where the result is a one-time link (team invite, set-password, role acceptance), which is shown on a 201 page instead because it is never shown again. A JSON body gets 200 or 201 with a `Location`, or problem+json with an `errors` object per field (422). API routes never redirect. On a submission, the deadline is checked before the body is validated, so a closed event answers 409 even to a body with missing fields; malformed JSON is 400. A refused request rolls back everything it wrote.

## Routes

- Service: `/healthz`, `/readyz`, `/about/access` (the policy table in words).
- Accounts: `/signup`, `/login`, `/logout`, `/password/<token>` (one-time set-password link), `/accept/<token>` (accept a judge or organizer role offered to an existing account), `/account` (your roles, change password). Demo mode only: `/demo/enter/<slug>`.
- Events: `/` and `/e` (list; `POST /e.json` creates one, admins), `/e/new`, `/e/<event>`, `/e/<event>/settings`, `/state`, `/criteria`, `/people`, `/people/<person>/password-link`.
- Teams: `/e/<event>/teams`, `/teams/<team>`, `/teams/<team>/invites`, `/invites/<id>/revoke`, `/leave`, `/members/<person>/remove`; `/join/<token>`.
- Submissions: `/e/<event>/projects` (the gallery; POST creates a draft), `/projects/new`, `/projects/<id>` (GET; POST or PATCH edits), `/edit`, `/submit`, `/withdraw`, `/media`, `/media/<n>`, `/media/<n>/delete`.
- Judging: `/e/<event>/judge/batches`, `/judge/assignments/<project>` with `/scores` and `/finalize`, `/judges/me/scores`, `/judges/<id>/scores`.
- Organizing: `/e/<event>/progress`, `/scores`, `/assignments`, `/assignments/<judge>/<project>/unlock`, `/assignment-runs`, `/assignment-runs/<id>`, `/batches/<id>/abandon`, `/results`, `/publish`, `/normalization`, `/normalization/<table>`, `/duplicates`, `/duplicates/<id>`, `/duplicates/<id>/confirm`, `/audit`.

`tests/test_authz_matrix.py` fails when a route is added without a row in its matrix.

## Layers

- `samepage/domain/`: exact-fraction weighted totals, the state machines, the deadline message, CSV cell guarding, canonical JSON and the ranking hash, demo token derivation. No Django.
- `samepage/engine/`: the Woodbury profile REML, z-scores, k=10 shrinkage, rank draws, the snapshot, bipartite assignment. NumPy only. `.importlinter` (checked in CI) keeps both of these free of Django and of the web layers.
- `samepage/services/`: the only writers. `accounts`, `events`, `teams`, `submissions`, `judging`, `duplicates`, `results` (snapshots, freshness, publish), `ledger` (the rows behind every number), `audit`, `seed` (the demo importer), `guards` (the publish freeze), `access` (roles, then the policy).
- `samepage/apps/portal/`: models, migrations (including the trigger SQL), the resource views and the templates' tag library.
- `samepage/core/`: the view base, bearer auth, CSRF for anonymous cookie writes, renderers, errors, the policy tables, headers, the throttle.
- `samepage/ops/`: the container entrypoint, the production preflight, the database role handoff, the healthcheck.
- `tools/`: `verify.py` (writes the receipts), `lifecycle_check.py` (one event over HTTP), `oracle_statsmodels.py` (the outside check). Standard library only, except the oracle.

`APPEND_SLASH` is off. There is no Django admin and no browsable API, because both redirect, and `run.py` follows a 302 into a 200. The first admin of a production instance comes from `manage.py samepage_admin` ([OPERATIONS.md](OPERATIONS.md#production)); everything after that is in the portal.

## Results

The results page never fits on a write. A snapshot stores the fitted payload and a fingerprint of its inputs. A read of the results or the lab compares the fingerprint with the inputs now; if they differ it refits first, holding a row lock on the event so two readers do not fit twice. The fit with leave-one-judge-out takes about 3 seconds on the seed. Publish stamps one snapshot and from then on every reader gets exactly that one ([JUDGING.md](JUDGING.md#what-counts)). If the fit raises, or takes longer than `SAMEPAGE_ENGINE_BOOT_BUDGET_S` (30 s by default; 0 switches the model off), the snapshot holds the fallback ranking by mean weighted total, and the page says so. `scores.csv` never waits on the engine.

## Readiness

`/healthz` is process liveness and never touches the database. `/readyz` runs `SELECT 1` and answers 503 problem+json when Postgres cannot be reached within the 5 second connect timeout. Both run outside the per-request transaction, because opening that transaction is what fails first when Postgres is down.

## Roles in the database

Migrations run as the owner. When `DB_OWNER_URL` is set (Compose sets it), every boot creates or updates the `samepage_app` role and re-grants: it may read and write the tables, may insert into `score_rev` and `audit_event` but not update or delete them, and owns nothing, so it cannot disable the triggers. Before serving, the entrypoint connects as `samepage_app` and refuses to start if it is a superuser, can bypass row security, can update `score_rev` or owns it. Then it drops `DB_OWNER_URL` from the environment and execs gunicorn as that role. Doing this on every boot, rather than in an init script in `docker-entrypoint-initdb.d`, means a volume that already has data still gets the grants.

With only `DATABASE_URL` set (local development, the tests), there is no handoff: the app runs as whatever role the URL names.

## Trade-offs

- Server-rendered pages and one small script, no SPA or Node build: the pages work without JavaScript except autosave, and the same view serves the API.
- Postgres for everything, including images (as bytes) and the throttle counter: one `pg_dump` is the whole backup, the app container keeps a read-only root, and every gunicorn worker shares one sign-in limit. The cost is a database that grows with uploads (2 MB cap per image).
- Refit on read instead of on write: a judge finalizing 30 projects does not wait for 30 fits, and the fingerprint makes a stale ranking impossible to serve.
- Isolation in one policy module rather than Postgres row-level security: simpler to read and test (every route in the matrix), but a view that forgot to call it would be a bug the database would not catch.

The numbered decisions are in [DECISIONS.md](DECISIONS.md).
