# Samepage

A self-hosted hackathon submission and judging portal. Every number on a page opens as the rows behind it: each list is also a CSV file and a JSON file, built from the same rows through the same policy check. Tools we did not write can audit it: the organizers' `run.py`, and a separate statsmodels image that re-derives the published ranking from the `scores.csv` an organizer downloads.

Claimed tiers: **T1 and T2**. `run.py` prints `claimed T1 T2, verified T1 T2` (see `acceptance-report.txt`, produced by the CI run of `docker compose up`). `run.py` checks seven things; the rest of each tier is checked by the tests and by `tools/lifecycle_check.py`, which drives one whole event over HTTP in production mode in CI (receipts below). What is still missing is in Limits.

| Tier bullet | State |
|---|---|
| T1 login, roles | Built. Sign-up with a hashed password (Django PBKDF2), sign-in (CSRF-checked, throttled), sign-out, change password, and one-time set-password links for the judges and organizers an organizer invites. Five roles: visitor, participant, judge, organizer (per event) and admin (global), from one policy table checked before any row is loaded. Demo accounts and tokens exist only in demo mode. |
| T1 create an event | Built. Admins create events at `/e/new` or `POST /e.json`: submission window and judging end (UTC), tracks, prize categories, rubric, custom questions, team size, blind judging. Organizers edit settings, add tracks and prizes, and move the state draft → open → closed → judging. |
| T1 form a team | Built. Start a team, invite by secret link (only its hash is stored; it expires, has a use limit and can be revoked), join, leave; organizers remove members. One team per person per event; judges and organizers of the event cannot join one. |
| T1 submit a project | Built. HTML form and `POST /e/<event>/projects.json`: name, tagline, description, thumbnail, up to 6 gallery images (PNG, JPEG, GIF or WebP, type sniffed from the bytes, stored in Postgres), video, repo and live URLs, tech tags, track, and the organizer's custom questions (a required one must be answered to submit). |
| T1 edit until the deadline | Built. A submission starts as a draft that only its team and the organizers can see. The team edits it (form, or `PATCH .json`), submits it, or withdraws it. After the deadline the service answers 409 and database triggers refuse content and image changes. |
| T1 deadline stops submissions | Built, twice: the service returns 409 and a trigger refuses the insert or the edit. |
| T1 public gallery | Built. Server-rendered HTML, JSON and CSV, no login: search over name, tagline, description and tags; any-of track filter; all-of tag filter; the same filters on every format. Drafts are not listed. |
| T2 invite and assign judges | Built. Invite by email with a role and tracks (a new person gets a one-time set-password link; an existing account gets a one-time acceptance link and holds the role only after accepting it while signed in; nothing is emailed, the portal is offline). Issue batches with the matcher (reviews per project, most per judge), top up short projects (unfinished work from an abandoned batch is reassigned), assign one pair by hand, or dry-run a design. Track eligibility and conflicts of interest are enforced; every run is audited. |
| T2 rubric the organizer can weight | Built. Event weights and per-track overrides on the settings page or `POST /e/<event>/criteria.json`. Criteria are fixed once the first score exists; weights can change until publish; each change is audited and the next results read refits. |
| T2 judges cannot see each other's work | Built. 403 before the target id is loaded, in HTML, JSON and CSV. A judge scores only their own assignments. |
| T2 progress view | Built. Counted, excluded, fully reviewed, short and withdrawn numbers, each linked to its CSV and checked against it on every request; judges with open work first; batches; the assignment ledger. |
| T2 evening out harsh and generous judges | Built. Profile REML with a fixed grid, shown beside raw means and Raptors k=10 (JUDGING.md). Only finalized reviews count. Results refit when their inputs change and are frozen at publish. |
| T2 CSV export | Built. Scores, projects, progress, results, assignments, runs, people, teams, rubric, audit, duplicates and the lab tables. Formula-guarded cells, no literal `null`. |

## Run it

```
docker compose up --wait
python run.py .dogfood.toml
```

The first build pulls the base images (pinned by digest, amd64 and arm64). After that nothing at runtime needs the network. The portal is on http://localhost:8080, published on 127.0.0.1 only. `fixtures.json` sits next to `run.py` and is also inside the image, where the boot seeds it.

On Windows use `python`, and `curl.exe` rather than PowerShell's `curl` alias. The checker is stdlib only. Running the app without Docker needs Python 3.12 and Postgres (OPERATIONS.md).

## Demo mode

`docker compose up` starts in demo mode (`SAMEPAGE_MODE=demo`). The boot log prints the four bearer headers in `.dogfood.toml`; they are HMACs of a fixed string, so they are the same on every fresh volume. Each page has a demo bar with one button per account. The button is a POST with a CSRF token, so a link or an image on another site cannot sign a browser in. The shared password is `samepage-demo`. Anyone can also create a real account at `/signup`.

| Who | Account | Lands on |
|---|---|---|
| Organizer | organizer@example.org | `/e/evt_01/progress` |
| Judge A (jdg_08) | marek.nowak@example.org | `/e/evt_01/judge/batches` |
| Judge B (jdg_03) | priya.nair@example.org | `/e/evt_01/judge/batches` |
| Participant | priya1@example.org | `/e/evt_01/projects` |
| Participant on the open event | control@example.org | `/e/evt_02/projects` |
| Admin | admin@example.org | `/e/evt_01/progress` |

evt_01 is the fixture: closed, in judging, with its 126 imported reviews and the Dry Harbour duplicate awaiting a decision. The demo seed also gives Judge A and Judge B one open batch each (two projects in their tracks they have not reviewed, run `run_demo`, audited), so the judge console has work on a fresh volume. evt_02 is an open event for trying the participant side. DEMO.md walks the whole lifecycle on a new event.

Everything in this section is public, so production mode refuses it. With `SAMEPAGE_MODE=production` (the default outside compose) the demo bar and `/demo/enter/*` are 404, demo bearer tokens get 401, the demo password never signs in, and the process refuses to start while demo tokens or demo passwords are in the database, or while the secret key, a database password or `ALLOWED_HOSTS=*` is a default (`samepage/ops/preflight.py`). A production database starts empty: `python manage.py samepage_admin --email you@example.org` makes the first admin (OPERATIONS.md). CI proves both halves: a demo-seeded volume is refused, and a fresh production volume boots, answers 401 to the demo organizer token, and then runs a whole event through `tools/lifecycle_check.py`.

## The checks a judge can do

**1. The organizers' checker.** `python run.py .dogfood.toml` ends in `claimed T1 T2, verified T1 T2`.

**2. A number opens as its rows.** Sign in as the organizer and open `/e/evt_01/progress`. The sentence is "121 counted + 5 excluded = 126". The "5 excluded" link is `scores.csv?counted=false`: five rows, all `prj_07`, each `withdrawn_duplicate:dup_01`. The footer says how many of the six numbers match the row count of the CSV they link to. It renders each linked CSV through the same code as the download, parses it and counts the rows on every request, and names any number that disagrees.

```
curl.exe -s -H "Authorization: Bearer <organizer token from .dogfood.toml>" http://localhost:8080/e/evt_01/scores.csv
```

**3. statsmodels re-derives the ranking.** With the stack up:

```
docker compose --profile oracle run --rm oracle
```

The oracle image holds statsmodels, pandas and scipy and no Samepage code. It downloads `scores.csv` with the organizer token, fits statsmodels' own MixedLM (a fixed effect per project, a random intercept per judge), evaluates its REML likelihood on the λ grid in JUDGING.md, and compares with `/e/evt_01/results.json`: λ, every review count, every adjusted score, every rank and `ranking_sha256`. It exits 1 on any difference. On the seeded fixture it reports λ 15.32391847910442 on both sides and the same ranking hash. The grid is ours; the likelihood and the effects are statsmodels'. Two projects (prj_09, prj_17) have the same judges and the same scores, so their effects are equal; the oracle checks they hold the same two rank positions and takes their order from the portal's documented tie-break. CI runs it on amd64 and arm64.

**4. One whole event, over HTTP.** With a portal up and an admin password, `python tools/lifecycle_check.py --base http://localhost:8080 --admin-email <admin>` (stdlib only) creates an event, signs three people up, forms teams (one by invite link), submits and edits drafts, invites three judges who set their passwords, moves the deadline to a few seconds ahead, waits for it and checks that edits are refused, issues batches, scores and finalizes every assignment, publishes, and reads the frozen results as a stranger. On the demo stack the admin is `admin@example.org` with `SAMEPAGE_ADMIN_PASSWORD=samepage-demo`.

**5. The tests.** `docker compose --profile test run --rm test` runs pytest inside the image against the compose Postgres: the HTTP role and format matrix, accounts, events, teams and invites, drafts and the deadline (service and triggers), images, the gallery filters, assignment, the weighted rubric, drafts not counted, unlock, the fixture's awkward cases in the fit, publish and its freeze, production refusals, CSRF on sign-in, write validation, the progress recount and the REML fit. CI also runs them natively.

## Receipts

Every file here is the output of a command, not typed. CI (`.github/workflows/acceptance.yml`) writes them with `tools/verify.py` (standard library only). After a green run, `python tools/verify.py fetch` copies them from it with `gh run download` and writes `receipts/ci-run.txt`, which names the run, the commit and each job's conclusion. `fetch` refuses a run that is not green, a run whose amd64 and arm64 reports differ, and a run that tested code other than this checkout's (only receipts and `*.md` may have changed since).

- `acceptance-report.txt`: `python tools/verify.py stack` against a cold `docker compose up` on amd64 (arm64 gives the same bytes). It runs `run.py .dogfood.toml`, then the tests and the oracle below, then `run.py` again, and fails unless both reports are `claimed T1 T2, verified T1 T2` and identical.
- `receipts/tests.txt`: `docker compose --profile test run --rm test` (pytest inside the image, against the compose Postgres), from the same `verify.py stack` step.
- `receipts/oracle-statsmodels.txt`: `docker compose --profile oracle run --rm oracle` against that stack, from the same step.
- `receipts/backup-restore.txt`: `python tools/verify.py backup` on that stack: the documented backup command, then a change (the Dry Harbour duplicate is merged), then the documented restore command. It fails unless `scores.csv`, the audit log length, the audit chain and the duplicate decision are back to what they were at the backup, and `run.py` still passes.
- `receipts/production-refusal-demo-db.txt`, `receipts/production-mode.txt`, `receipts/production-lifecycle.txt`, `receipts/readiness-db-down.txt`: `python tools/verify.py production`, with random secrets. Production mode refuses a volume first seeded in demo mode and leaves `samepage_app` untouched; on a fresh volume it boots and refuses the demo sign-in and the demo organizer token; `manage.py samepage_admin`, then `tools/lifecycle_check.py` runs one event from creation to published results, request by request (one-time link secrets are cut to their first characters); with the database container stopped, `/healthz` is 200, `/readyz.json` 503 problem+json and an API URL 500 problem+json.
- `receipts/inputs.txt`: sha256 of `run.py` and `fixtures.json` (`python tools/verify.py inputs`, also run by `fetch`), identical to the organizers' files.

## What that proves

| Proves | Does not prove |
|---|---|
| Refusal lives in the backend and covers HTML, JSON and CSV. A judge asking for another judge's scores gets 403, not an empty page. | That a database superuser cannot edit a row. The audit chain and a downloaded CSV detect that afterwards. Nothing is signed. |
| The REML fit is the GLS estimator at the λ that maximises the profile likelihood on a fixed grid. statsmodels, an independent implementation, gets the same λ and ranking. A dense inverse agrees with the Woodbury form to about 1e-15 (the test asserts 1e-9). | That the model suits this data. The project signal is tiny. The results page says the top 5 is a statistical tie. |
| The progress numbers equal the row counts of the CSVs they link to, checked on every request. | Anything about T3 or T4. We do not claim them. |

## Limits

Known gaps, not hidden:

- Nothing is emailed. Team invite links, set-password links and role acceptance links are shown once, to the person who created them, to pass on by hand. The portal runs offline by design.
- On an event too small for the judge-bias fit (within every project, all reviews agree), results fall back to the plain mean of the weighted totals with no judge adjustment, and the results page says so (JUDGING.md, "When the model cannot be fitted").
- There is no self-service password reset. An operator runs `python manage.py changepassword <email>`. An organizer can hand out a set-password link only for an account that has never had a password and has no role on another event.
- Tracks, prize categories and events cannot be deleted from the UI, only added; event states only move forward. An issued assignment cannot be withdrawn, only its batch abandoned (its unfinished work is then topped up to other judges).
- The public gallery shows every track to everyone, judges included. Track scoping applies to judging: a judge is assigned, sees in the console and scores only projects in their tracks, and reads only their own scores.
- Images are stored as they were uploaded (2 MB each, no resizing). There is no virus scan; the type is sniffed from the bytes and served with a sandboxing CSP.
- Sign-up is open to anyone who can reach the portal (throttled, CSRF-checked). There is no captcha or email verification.
- T3 is not built. No webhooks, certificates, signed records, OpenAPI file or embeddable widget.
- Raw and k=10 ranks in the lab break exact ties by float noise rather than by the documented submission-time rule.
- Read isolation is one policy module in application code, not Postgres row-level security.
- The runtime database role cannot update `score_rev` or the audit log and does not own the tables, so it cannot disable those triggers. The owner password is still in the app container for migrations. A host operator can edit rows. A downloaded CSV is the witness.

## Layout

Django 5.2, Django REST Framework, Postgres 16, gunicorn, WhiteNoise, Pico CSS (vendored, MIT, see NOTICE) and a small `console.js`. Numpy is the only maths library in the runtime image. The oracle image is separate.

`samepage/domain/` and `samepage/engine/` import no Django (`.importlinter`, checked in CI). Views call services. Services are the writers. ARCHITECTURE.md, DATA-MODEL.md, JUDGING.md, THREAT_MODEL.md and OPERATIONS.md have the details.

## Tests

```
docker compose --profile test run --rm test
```

Natively, with Python 3.12 and a Postgres the tests may create a database on:

```
pip install -r requirements-dev.txt
DATABASE_URL=postgres://owner:password@127.0.0.1:5432/samepage python -m pytest
```

Without `DATABASE_URL` only the pure tests (policy tables, REML, rules) run; the database tests are skipped and say so. `tests/test_lifecycle.py` (T1) and `tests/test_judging_flow.py` (T2) drive the flows through the same URLs a browser uses.

## License

Apache License 2.0 (LICENSE). Pico CSS is MIT (NOTICE).
