# Threat model

## Covered

| Threat | What we do | Where it is tested |
|---|---|---|
| A judge reads a peer's scores by URL | `scores.read_named` is denied unless the slug is the caller's own id, or the caller is staff. The check runs before the row is loaded. 403 in HTML, JSON and CSV, also for ids that do not exist. | `tests/test_http.py`, `run.py` |
| A participant opens a score URL | `scores.read_own` requires the judge role. 403, including on `/judges/me/scores`. | `tests/test_http.py`, `run.py` |
| Deadline bypass by a client clock | The service and a trigger both compare with the database clock. Imports are judged on `submitted_at`, so seeding a closed event does not trip the trigger. | `run.py` (409), `tests/test_http.py` |
| Format confusion | The suffix wins. `URL_FORMAT_OVERRIDE` is none. Unknown suffixes are 404. | |
| Web cache deception | A path like `/scores.json/x.csv` is not a route. | |
| CSRF on cookie sessions | Enforced for signed-in writes (DRF session authentication) and for the anonymous writes that start a session, `POST /login`, `POST /signup`, `POST /password/<token>` and `POST /demo/enter/<slug>`, which check the token themselves. Bearer requests are exempt because they are not cookie sessions. | `tests/test_sessions.py` |
| Login CSRF through a GET | `/demo/enter/<slug>` answers a GET with a page and a button; only the POST signs in. | `tests/test_sessions.py` |
| Password guessing | `POST /login` is throttled to 10 a minute per client address (the TCP peer unless `SAMEPAGE_NUM_PROXIES` is set). The count is kept in Postgres, so every gunicorn worker shares it. GET routes are never throttled. | `tests/test_sessions.py` |
| Login redirect hiding a 401 | No redirects on refusal. The sign-in form is rendered with status 401 and `WWW-Authenticate: Bearer`. | `tests/test_http.py` |
| Tracebacks in error bodies | DEBUG is off outside demo mode and off by default in demo mode. A 500 returns a problem body with a reference id and no stack; the stack goes to the log with the same id. | `tests/test_writes.py` |
| Bad input causing 500s | Bodies must be objects, text fields must be text, tracks must belong to the event, a final score is 409, an illegal state change is 409, a trigger refusal is 409. Refused requests roll back. | `tests/test_writes.py` |
| Formula injection in CSV | Text cells with a spreadsheet trigger get a leading quote. | `tests/test_writes.py` |
| XSS | Templates autoescape. User fields are not marked safe. The CSP is `default-src 'self'` with no inline script. | |
| Public demo credentials in production | Production mode refuses to start while demo tokens or the demo password are in the database, or while the secret key, a database password or `ALLOWED_HOSTS=*` is a default. At request time a demo token is 401, the demo password never signs in, and `/demo/enter/*` is 404. | `tests/test_production.py`, CI `production` job |
| Stolen or guessed invite links | Team links are 24 random bytes, stored as sha256 only, shown once, with an expiry, a use limit and revoke. Joining needs an account; judges and organizers of the event cannot join; a team has a size cap; team changes stop at the deadline. Each create, join and revoke is audited. | `tests/test_lifecycle.py` |
| Account takeover through a set-password link | A link is one use, expires in 14 days, and a new link revokes the old. An organizer gets one only for an account that has never had a password and has no role on another event, so an organizer of one event cannot take over a judge, an admin or anyone else's account. | `tests/test_judging_flow.py` |
| Password guessing at sign-up or with a link | Sign-up and set-password share the sign-in throttle and check CSRF. Passwords are PBKDF2 hashes, 10 characters or more, and never the published demo password. | `tests/test_lifecycle.py` |
| Hostile uploads | Images only: the type is sniffed from the first bytes (PNG, JPEG, GIF, WebP; SVG and HTML are refused), at most 2 MB, served with the sniffed type, `nosniff` and `Content-Security-Policy: default-src 'none'; sandbox`. A draft's images are private like the draft. | `tests/test_lifecycle.py` |
| Changing a submission after the deadline | The service answers 409, and triggers refuse content edits and image changes in the database. | `tests/test_lifecycle.py` |
| Changing the outcome after publish | Scores, unlocks, weights, duplicate decisions and assignment runs answer 409 once published, and readers get the snapshot stamped at publish. | `tests/test_judging_flow.py` |
| A draft or reopened score deciding the ranking | Only reviews whose every criterion is final are counted; the rest are in `scores.csv` with the reason. | `tests/test_judging_flow.py` |
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
- **Open sign-up.** Anyone who can reach the portal can create an account. An account alone reaches nothing private: it can start or join a team with a link.
- **The public gallery shows every track to judges.** Track scoping covers assignment, the console and scores, not the public gallery (JUDGING.md, Assignment).
