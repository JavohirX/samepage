# Threat model

## Covered

| Threat | What we do | Where it is tested |
|---|---|---|
| A judge reads a peer's scores by URL | `scores.read_named` is denied unless the slug is the caller's own id, or the caller is staff. The check runs before the row is loaded. 403 in HTML, JSON and CSV, also for ids that do not exist. | `tests/test_http.py`, `run.py` |
| A participant opens a score URL | `scores.read_own` requires the judge role. 403, including on `/judges/me/scores`. | `tests/test_http.py`, `run.py` |
| Deadline bypass by a client clock | The service and a trigger both compare with the database clock. Imports are judged on `submitted_at`, so seeding a closed event does not trip the trigger. | `run.py` (409), `tests/test_http.py` |
| Format confusion | The suffix wins. `URL_FORMAT_OVERRIDE` is none. Unknown suffixes are 404. | |
| Web cache deception | A path like `/scores.json/x.csv` is not a route. | |
| CSRF on cookie sessions | Enforced for signed-in writes (DRF session authentication) and for the two anonymous writes that start a session, `POST /login` and `POST /demo/enter/<slug>`, which check the token themselves. Bearer requests are exempt because they are not cookie sessions. | `tests/test_sessions.py` |
| Login CSRF through a GET | `/demo/enter/<slug>` answers a GET with a page and a button; only the POST signs in. | `tests/test_sessions.py` |
| Password guessing | `POST /login` is throttled to 10 a minute per client address (the TCP peer unless `SAMEPAGE_NUM_PROXIES` is set). The count is kept in Postgres, so every gunicorn worker shares it. GET routes are never throttled. | `tests/test_sessions.py` |
| Login redirect hiding a 401 | No redirects on refusal. The sign-in form is rendered with status 401 and `WWW-Authenticate: Bearer`. | `tests/test_http.py` |
| Tracebacks in error bodies | DEBUG is off outside demo mode and off by default in demo mode. A 500 returns a problem body with a reference id and no stack; the stack goes to the log with the same id. | `tests/test_writes.py` |
| Bad input causing 500s | Bodies must be objects, text fields must be text, tracks must belong to the event, a final score is 409, an illegal state change is 409, a trigger refusal is 409. Refused requests roll back. | `tests/test_writes.py` |
| Formula injection in CSV | Text cells with a spreadsheet trigger get a leading quote. | `tests/test_writes.py` |
| XSS | Templates autoescape. User fields are not marked safe. The CSP is `default-src 'self'` with no inline script. | |
| Public demo credentials in production | Production mode refuses to start while demo tokens or the demo password are in the database, or while the secret key, a database password or `ALLOWED_HOSTS=*` is a default. At request time a demo token is 401, the demo password never signs in, and `/demo/enter/*` is 404. | `tests/test_production.py`, CI `production` job |
| Team identity under blind judging | When an event has blind judging on, judges do not receive team name or id from the gallery in HTML, JSON or CSV, decided by the field policy table. | `tests/test_writes.py` |

Cache-Control is `private, no-store` on every credentialed response and every 4xx or 5xx. Anonymous public GETs of the gallery, and of results after publish, are `public, max-age=30` with `Access-Control-Allow-Origin: *`. Unpublished results are 403 with `no-store`, including for anonymous clients.

## Accepted

- **403 leaks existence** of a judge id. A 404 would fail the checker and would also be a different leak. We take the 403.
- **A database owner can edit rows.** Triggers stop the runtime role and stop ordinary bugs. They do not stop the owner. The audit hash chain and any downloaded CSV show the change afterwards. Nothing is signed.
- **No row-level security.** Isolation is the policy module. A view that forgot to call it would be a bug. Every route calls it in `SamepageView.initial`.
- **The owner password is in the app environment** during migrate, and Compose passes it in. Anyone who can `docker exec` into the app container is the owner.
- **Demo mode is open on purpose.** Anyone who can reach a demo-mode portal can press a demo button and be the organizer. Compose publishes the port on 127.0.0.1 only for that reason.
- **The gallery shows each project's review count** to visitors before results are published.
- **T3 is absent.** There is no ballot to stuff. That is a missing feature, stated in the README, not a defence.
- **Published results are not frozen** (README, Limits). Every change is still in the audit chain.
