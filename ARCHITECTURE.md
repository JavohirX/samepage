# Architecture

One URL is one resource. The suffix picks the format.

- `/e/evt_01/scores` is HTML for a browser, and for `run.py`, which sends no Accept header.
- `/e/evt_01/scores.json` is JSON. The top-level value is an object.
- `/e/evt_01/scores.csv` is RFC 4180 CSV.

All three go through one view class (`SamepageView`), one `policy.allows` check, one query, and one list of dicts. Only the renderer differs. Suffixed patterns are registered first, with slug converters, so `prj_01.json` is not captured as an id. `?format=` is disabled. An unknown suffix is 404. `/judges/me/scores.json/x.csv` does not match a route, so it is 404 rather than a cached private body.

## Request order

1. Bearer authentication, if an Authorization header is present. A bad bearer is 401 and does not fall back to a cookie.
2. Session authentication otherwise. Cookie writes need a CSRF token. Bearer writes do not.
3. `policy.allows`, before the target id is loaded. A judge opening another judge's scores is 403 even when that judge does not exist.
4. The service builds the rows.
5. The renderer. Errors are plain Django responses. A DRF response on a `.csv` route would be re-rendered as CSV and become a 500, which fails `run.py`.

Writes use the same view. The suffix, if any, picks the response. Otherwise a form body gets a 303 or a re-rendered form, and a JSON body gets 201 or problem+json. The deadline is checked before field validation, so a closed event returns 409 even when the JSON is missing fields. Malformed JSON is 400.

## Layers

- `samepage/domain/` — fractions, state machines, the deadline clock message, CSV guarding, canonical JSON. No Django.
- `samepage/engine/` — Woodbury profile REML, z-scores, k=10, rank draws, bipartite assignment. Numpy only.
- `samepage/services/` — the only writers. Audit appends, the importer, duplicate decisions, snapshots.
- `samepage/apps/portal/` — models and the resource views.
- `samepage/core/` — the view base, auth, renderers, errors, policy tables, headers.

`APPEND_SLASH` is off. There is no Django admin and no browsable API, because both redirect, and `run.py` would follow a 302 into a 200.

## Readiness

`/healthz` is process liveness. `/readyz` checks the database. Neither waits on the REML fit. If the fit raises or the boot budget is 0, results fall back to raw means and say so. `scores.csv` never waits on the engine.

## Roles in the database

Migrations run as the owner. Every boot creates `samepage_app` if needed and re-grants. That role can insert into `score_rev` and `audit_event` and cannot update or delete them, and it does not own the tables, so it cannot disable the triggers. Gunicorn then runs as that role. A volume that already has data still gets the grants, which an init script in `docker-entrypoint-initdb.d` would skip.

Local development can use a single superuser URL. Docker Compose sets `DB_OWNER_URL` and does the handoff.
