# Architecture

One URL is one resource. The suffix picks the format.

- `/e/evt_01/scores` is HTML for a browser, and for `run.py`, which sends no Accept header.
- `/e/evt_01/scores.json` is JSON. The top-level value is an object.
- `/e/evt_01/scores.csv` is RFC 4180 CSV.

All three go through one view class (`SamepageView`), one `policy.allows` check, one query, and one list of dicts. Only the renderer differs. Suffixed patterns are registered first, with slug converters, so `prj_01.json` is not captured as an id. `?format=` is disabled. An unknown suffix is 404. A 404 or 500 raised before any view runs still follows the URL: a `.json` or `.csv` URL gets problem+json, not an HTML page. `/login` is HTML only and has no suffixed twin. `/judges/me/scores.json/x.csv` does not match a route, so it is 404 rather than a cached private body.

## Request order

1. Bearer authentication, if an Authorization header is present. A bad bearer is 401 and does not fall back to a cookie.
2. Session authentication otherwise. Cookie writes need a CSRF token. Bearer writes do not.
3. `policy.allows`, before the target id is loaded. A judge opening another judge's scores is 403 even when that judge does not exist.
4. The service builds the rows.
5. The renderer. Errors are plain Django responses. A DRF response on a `.csv` route would be re-rendered as CSV and become a 500, which fails `run.py`.

Writes use the same view. The suffix, if any, picks the response. Otherwise a form body gets a 303 to the page that shows the result, and a JSON body gets 200 or 201 with a `Location`, or problem+json with an `errors` object per field. API routes never redirect. The deadline is checked before field validation, so a closed event returns 409 even when the JSON is missing fields. Malformed JSON is 400. DRF's own content negotiation is replaced by one that never answers 406, because the view chooses the format.

A view declares `action` (what reading the URL needs) and, where a POST needs more, `write_action`; `SamepageView.initial` checks the one that applies before the handler runs. Object-level rules (a member of this team, an assignment of this judge, a draft of this team) are checked in the service before the row is returned or written.

## Routes

- Accounts: `/signup`, `/login`, `/logout`, `/password/<token>` (one-time link), `/accept/<token>` (accept a judge or organizer role offered to an existing account), `/account` (roles, change password).
- Events: `/e` (list; POST creates, admins), `/e/new`, `/e/<event>`, `/e/<event>/settings`, `/e/<event>/state`, `/e/<event>/criteria`, `/e/<event>/people`.
- Teams: `/e/<event>/teams`, `/e/<event>/teams/<team>` with `/invites`, `/invites/<id>/revoke`, `/leave`, `/members/<person>/remove`; `/join/<token>`.
- Submissions: `/e/<event>/projects` (gallery; POST creates a draft), `/projects/new`, `/projects/<id>` (GET; POST or PATCH edits), `/edit`, `/submit`, `/withdraw`, `/media`, `/media/<n>`, `/media/<n>/delete`.
- Judging: `/e/<event>/judge/batches`, `/judge/assignments/<id>` with `/scores` and `/finalize`, `/judges/me/scores`, `/judges/<id>/scores`, `/assignments`, `/assignments/<judge>/<project>/unlock`, `/assignment-runs`, `/batches/<id>/abandon`, `/progress`, `/scores`, `/results`, `/publish`, `/normalization`, `/duplicates`, `/audit`.

## Layers

- `samepage/domain/` — fractions, state machines, the deadline clock message, CSV guarding, canonical JSON. No Django.
- `samepage/engine/` — Woodbury profile REML, z-scores, k=10, rank draws, bipartite assignment. Numpy only.
- `samepage/services/` — the only writers. `accounts`, `events`, `teams`, `submissions`, `judging`, `duplicates`, `results` (snapshots, freshness, publish), `ledger` (the rows behind every number), `audit`, the importer (`seed`), and `guards` (the publish freeze).
- `samepage/apps/portal/` — models and the resource views.
- `samepage/core/` — the view base, auth, renderers, errors, policy tables, headers.

`APPEND_SLASH` is off. There is no Django admin and no browsable API, because both redirect, and `run.py` would follow a 302 into a 200. The first admin of a production instance comes from `manage.py samepage_admin` (OPERATIONS.md); everything after that is in the portal.

## Readiness

`/healthz` is process liveness and never touches the database. `/readyz` checks the database and answers 503 problem+json when it cannot reach it. Both run outside the per-request transaction, because opening that transaction is what fails first when Postgres is down. Neither waits on the REML fit. If the fit raises or the boot budget is 0, results fall back to raw means and say so. `scores.csv` never waits on the engine.

## Roles in the database

Migrations run as the owner. Every boot creates `samepage_app` if needed and re-grants. That role can insert into `score_rev` and `audit_event` and cannot update or delete them, and it does not own the tables, so it cannot disable the triggers. Gunicorn then runs as that role. A volume that already has data still gets the grants, which an init script in `docker-entrypoint-initdb.d` would skip.

Local development can use a single superuser URL. Docker Compose sets `DB_OWNER_URL` and does the handoff.
