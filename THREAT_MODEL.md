# Threat model

## Covered

| Threat | What we do |
|---|---|
| A judge reads a peer's scores by URL | `scores.read_named` is denied unless the slug is the caller's own id, or the caller is staff. The check runs before the row is loaded. 403 in HTML, JSON and CSV. |
| A participant opens a score URL | `scores.read_own` requires the judge role. 403, including on `/judges/me/scores`, so we never 404 a non-judge. |
| Deadline bypass by a client clock | The service and a trigger both compare with the database clock. Imports are judged on `submitted_at`, so seeding a closed event does not trip the trigger. Content edits after close are refused. State and duplicate columns stay writable so an organizer can still resolve duplicates. |
| Format confusion | The suffix wins. `URL_FORMAT_OVERRIDE` is none. Unknown suffixes are 404. |
| Web cache deception | A path like `/scores.json/x.csv` is not a route. |
| CSRF on cookie sessions | Enforced. Bearer requests are exempt because they are not cookie sessions. |
| Login redirect hiding a 401 | No redirects on refusal. The sign-in form is rendered with status 401. |
| Tracebacks in error bodies | DEBUG is off. 500s return a problem body without a stack. |
| Formula injection in CSV | Text cells with a spreadsheet trigger get a leading quote. |
| XSS | Templates autoescape. User fields are not marked safe. |
| Demo tokens in production | Production mode refuses to boot while `demo=true` tokens exist, and refuses a default secret, a default database password, and `ALLOWED_HOSTS=*`. |
| Invite tokens | 32 random bytes, stored as sha256. The accept path is audited. |

Cache-Control is `private, no-store` on every credentialed response and every 4xx or 5xx. Anonymous public GETs of the gallery, and of results after publish, are `public, max-age=30` with `Access-Control-Allow-Origin: *`. Unpublished results are 403 with `no-store`, including for anonymous clients, so a cache cannot keep a denial and serve it after publish.

## Accepted

- **403 leaks existence** of a judge id. A 404 would fail the checker and would also be a different leak. We take the 403.
- **A database owner can edit rows.** Triggers stop the runtime role and stop ordinary bugs. They do not stop the owner. The audit hash chain and any downloaded CSV show the change afterwards. Nothing is signed.
- **No row-level security.** Isolation is the policy module. A bug in a view that forgets to call it is a bug. The score routes call it in `SamepageView.initial`.
- **The owner password is in the app environment** during migrate, and Compose passes it in. Anyone who can `docker exec` as root is the owner.
- **T3 is absent.** There is no ballot to stuff. That is a missing feature, stated in the README, not a defence.
- **Demo login links** (`/demo/enter/<slug>`) sign a browser in without a password. They 404 when demo mode is off.
