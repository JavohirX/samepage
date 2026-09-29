# Samepage

A self-hosted hackathon submission and judging portal: Django, Postgres and server-rendered pages, offline once built. Every number on a page opens as the rows behind it. Each list is also a CSV file and a JSON file, built from the same rows through the same policy check, so tools we did not write can audit it: the organizers' `run.py`, and a separate statsmodels image that re-derives the published ranking from the `scores.csv` an organizer downloads.

Built for DOGFOOD 2026. [`.dogfood.toml`](.dogfood.toml) claims **T1 and T2** and nothing else, and `run.py` prints `claimed T1 T2, verified T1 T2` ([acceptance-report.txt](acceptance-report.txt), from the CI run of `docker compose up`). What is not built is under [Limits](#limits).

## Quick start

You need Docker with Compose v2. The checker needs Python 3 on the host (standard library only).

```
docker compose up --wait
python run.py .dogfood.toml
```

The first command builds the image, starts Postgres, migrates, seeds `fixtures.json` and returns once the app is healthy. The second is the organizers' checker; its last line is `claimed T1 T2, verified T1 T2`. Then open http://localhost:8080. A plain `docker compose up` works too and keeps the log in the foreground.

The first build pulls the base images (pinned by digest, amd64 and arm64) and the Python wheels. After that nothing needs the network: CI boots the stack with container egress blocked and the checker still passes. The port is published on 127.0.0.1 only; Postgres is not published at all. On Windows type `python` (not `python3`) and `curl.exe` (not PowerShell's `curl`). To run without Docker (Python 3.12 and a Postgres), see [OPERATIONS.md](OPERATIONS.md#local-without-docker).

## Demo logins (evaluation only)

`docker compose up` starts in demo mode (`SAMEPAGE_MODE=demo`), which is open on purpose so you can try every role. Every page has a demo bar with one button per account; each button is a POST with a CSRF token, so a link or an image on another site cannot sign a browser in. Every demo account also takes the password `samepage-demo` at `/login`. For curl, `.dogfood.toml` holds four `Authorization: Bearer sp_demo_…` headers, and `docker compose logs app` prints them at every boot.

| Button | Account | What it can do | Lands on |
|---|---|---|---|
| Organizer | organizer@example.org | organizes evt_01 and evt_02 | `/e/evt_01/progress` |
| Judge A | marek.nowak@example.org (fixture judge jdg_08) | judges track trk_04 of evt_01 | `/e/evt_01/judge/batches` |
| Judge B | priya.nair@example.org (fixture judge jdg_03) | judges tracks trk_04 and trk_05 of evt_01 | `/e/evt_01/judge/batches` |
| Participant | priya1@example.org | on team tm_01 (NorthKiln) of evt_01 | `/e/evt_01/projects` |
| Participant (open event) | control@example.org | on the only team of evt_02 | `/e/evt_02/projects` |
| Admin | admin@example.org | global admin: creates events, organizes every event | `/e/evt_01/progress` |

The tokens are HMACs of a string in this repository, so they are the same on every fresh volume and anyone with the source can compute them. Never expose demo mode to a network. Production mode (`SAMEPAGE_MODE=production`, the default outside compose) seeds nothing, answers 404 to the demo buttons, 401 to a demo token, never accepts the demo password, and refuses to start while any demo credential or default secret is left ([OPERATIONS.md](OPERATIONS.md#production)). Anyone can also create a real account at `/signup`, in either mode.

What the seed holds:

- **evt_01**, "Sample Hack 2026", loaded from `fixtures.json`: 41 submissions, 30 judges, 8 tracks, 126 reviews, all final. Its deadline (2026-03-01) has passed, so it refuses submissions. It stops at `judging`, not published: the Dry Harbour duplicate (prj_07 and prj_41, one team) is resolved keep-latest but provisional, and publish answers 409 until an organizer confirms or switches it. That leaves 40 projects and 121 counted reviews. The seed also issues Judge A and Judge B one open batch of two projects each (run `run_demo`, audited), so the judge console has work.
- **evt_02**, "Open control", takes submissions until 2027-01-01, for trying the participant side.

[DEMO.md](DEMO.md) walks one new event from creation to published results, then tours the fixture.

## Tiers

`run.py` has checks for T1 and T2 only, so `.dogfood.toml` claims T1 and T2. It checks seven things; everything else in these tables is checked by the tests in `tests/` and by `tools/lifecycle_check.py`, which drives one whole event over HTTP (CI runs it in production mode on an empty database).

### T1 core: claimed, verified

| Requirement | State |
|---|---|
| Accounts and sessions | Built. Sign-up with a PBKDF2 password hash (10 characters or more, never the demo password), sign-in (CSRF-checked, throttled), sign-out, change password. Judges and organizers an organizer invites get a one-time set-password link. Bearer tokens exist in demo mode only. |
| Roles: visitor, participant, judge, organizer, admin | Built. Participant, judge and organizer are per event; admin is global. One policy table, [`samepage/core/policy.py`](samepage/core/policy.py), checked before any target row is loaded, and shown at `/about/access`. |
| Create an event: window, tracks, prize categories | Built. Admins create events at `/e/new` or `POST /e.json`: submission start and deadline, judging end (UTC), tracks, prize categories, weighted rubric, custom questions, team size, blind judging. Organizers then edit the settings, add tracks and prizes, and move the state draft → open → closed → judging (closing waits for the deadline). |
| Teams and invite links | Built. Start a team on the event page; invite by secret link (only its sha256 is stored; 7 days and 3 uses by default, revocable); join, leave; organizers remove members. One team per person per event. Judges, organizers and admins cannot be on a team. Teams are fixed once submissions close. |
| Draft, submit, edit until the deadline | Built. HTML form or `POST /e/<event>/projects.json`. A submission starts as a draft that only its team and the organizers can see (unless it is submitted at once); the team edits it (form or `PATCH`), submits it, or withdraws it. After the deadline only an organizer can withdraw it. |
| Submission fields | Built. Name, tagline, description, thumbnail, up to 6 gallery images (PNG, JPEG, GIF or WebP, type sniffed from the bytes, stored in Postgres), video, repository and live URLs (http and https only), tech tags, track, and the organizer's custom questions (a required one must be answered to submit). |
| Deadline enforced on the server | Built twice. After the deadline the service answers 409 before it validates the body, on the database clock, and database triggers refuse the insert, content edits and image changes. `run.py` check 3. |
| Public gallery with search and filters | Built. No login: search over name, tagline, description and tags; any-of track filter; all-of tag filter; the same filters in HTML, JSON and CSV. Drafts and withdrawn projects are not listed. `run.py` checks 1 and 2. |

### T2 judging: claimed, verified

| Requirement | State |
|---|---|
| Judge invitation and assignment | Built. Invite by email with a role and tracks. A new address gets an account and a one-time set-password link; an address whose account is already in use (it has a password, a role or a team) gets a one-time acceptance link and holds the role only after accepting it while signed in. Nothing is emailed: links are shown once to pass on by hand. Assignment: issue batches with the matcher (reviews per project, most per judge), top up short projects (unfinished work of an abandoned batch is handed on), assign one pair by hand, or dry-run a design. Track eligibility and conflicts are enforced and every run is audited. |
| Weighted rubric set by the organizer | Built. Event weights and per-track overrides on the settings page or `POST /e/<event>/criteria.json`. Criteria are fixed once the first score exists; weights can change until publish, each change is audited, and the next results read refits. |
| Role isolation at the API | Built. A judge asking for another judge's scores gets 403 before the id is loaded, in HTML, JSON and CSV, also for ids that do not exist; a participant gets 403 on every score URL; a stranger gets 401. Never a redirect. A judge scores and opens in the console only their own assignments. `tests/test_authz_matrix.py` checks every route for seven principals in every format. `run.py` checks 4 to 6. |
| Live progress dashboard | Built. `/e/<event>/progress`: counted, excluded, fully reviewed, short and withdrawn-duplicate numbers (a project a duplicate decision withdrew, not one its team or an organizer withdrew), each linked to its CSV and recounted from that CSV on every request; judges with open work first; batches with abandon; the assignment ledger with reopen. |
| Cross-judge normalization | Built. An additive judge-bias model fit by profile REML on a fixed grid, shown beside raw means and the Raptors k=10 shrinkage ([JUDGING.md](JUDGING.md)). Only finalized reviews count. Results refit when their inputs change and freeze at publish. statsmodels reproduces the ranking. |
| CSV at every stage | Built. Events, projects, teams, people, rubric, scores, progress, assignments, assignment runs, results, the lab tables, duplicates and the audit log; a judge's own scores and batches. Formula-guarded cells, no literal `null`. `run.py` check 7. |

### T3 Community & Public Engagement: Built & Verified

- **Quadratic Community Voting**: Quadratic credit allocations (`sum(credits^2) <= budget`), separate participant and public voting channels with configurable influence multipliers, voter email magic links, and audited tally snapshots (`/e/<event>/voting`, `/tally`).
- **Public Comments & Pre-moderation**: Public project comments with pre-moderation queue (`pending` → `approved`/`rejected`), comment rate throttles, and organizer moderation controls (`/e/<event>/projects/<project>/comments`, `/comments`).

### T4 Advanced Verification, Distribution & Ecosystem: Built & Verified

- **S7 Signed Evaluation Records & Judge Protocols**: RFC 9162 Merkle tree calculated over all counted reviews, Ed25519 signature over Merkle root (`root.txt`, `root.sig`, `pub.pem`, `/records/root`), and judge protocol generation with cryptographic audit inclusion proofs (`/e/<event>/judge/protocol`).
- **S8 Self-Contained SVG Certificates**: High-fidelity award certificates generated as stand-alone SVG images with embedded Ed25519 cryptographic signatures and public keys, verifiable online or offline (`/certificates/<cert_no>`, `/e/<event>/teams/<team>/certificate.svg`).
- **S9 Distribution-First Feedback Packs**: Team feedback packs with percentile rankings, ASCII/Unicode score distribution histograms, per-criterion means, anonymous judge comments, and audited organizer release gating (`/e/<event>/teams/<team>/feedback`, `/feedback`).
- **S10 Embeddable Gallery Widget**: Standalone embed widget script (`widget.js`) with responsive card layout, CORS headers, and embed code generator (`/e/<event>/embed`).
- **S11 OpenAPI 3.0 Specification & Swagger UI**: Full OpenAPI 3.0 schema generation at `/openapi.json` and `/api/v1/openapi.json` with interactive Swagger UI at `/docs`.
- **S12 Webhooks & Outbox Worker**: Standard Webhooks HMAC-SHA256 signatures (`webhook-id`, `webhook-timestamp`, `webhook-signature`), SSRF safety validation, and background delivery worker (`deliver_webhooks`).
- **S13 Portable Event Bundle Import & Export**: Roundtrip event export and import (`/e/<event>/export.json`, `POST /e/import.json`) matching and extending the native `fixtures.json` format.

## Checks you can run

**1. The organizers' checker.** `python run.py .dogfood.toml` ends in `claimed T1 T2, verified T1 T2`.

**2. A number opens as its rows.** Press **Organizer** and open `/e/evt_01/progress`. It reads "121 counted + 5 excluded = 126". The "5 excluded" link is `scores.csv?counted=false`: five rows, all prj_07, each `withdrawn_duplicate:dup_01`. Below, the page says how many of its six numbers match the row count of the CSV they link to: it renders each linked CSV through the same code as the download, parses it and counts the rows on every request, and names any number that disagrees.

```
curl.exe -s -H "Authorization: Bearer <organizer token from .dogfood.toml>" http://localhost:8080/e/evt_01/scores.csv
```

**3. statsmodels re-derives the ranking.** With the stack up:

```
docker compose --profile oracle run --rm oracle
```

The oracle image holds statsmodels, pandas and scipy and no Samepage code. It downloads `scores.csv` with the organizer token, fits statsmodels' own MixedLM (a fixed effect per project, a random intercept per judge), evaluates its REML likelihood on the grid in JUDGING.md, and compares with `/e/evt_01/results.json`: λ, every adjusted score, every rank and `ranking_sha256`. It exits 1 on any difference. On the seed both sides give λ 15.32391847910442 and the same ranking hash. The grid is ours; the likelihood and the effects are statsmodels'. Two projects (prj_09, prj_17) have the same judges and the same scores, so their effects are equal; the oracle checks they hold the same two ranks and takes their order from the portal's documented tie-break. Without Docker: `pip install -r requirements-oracle.txt`, then `python tools/oracle_statsmodels.py --toml .dogfood.toml`.

**4. One whole event over HTTP.** `python tools/lifecycle_check.py --base http://localhost:8080 --admin-email admin@example.org` with `SAMEPAGE_ADMIN_PASSWORD=samepage-demo` in the environment (standard library only; on a production instance use your admin). It creates an event, signs up four people who form three teams (one joins by invite link), submits and edits drafts, invites three judges who set their passwords, moves the deadline a few seconds ahead, waits and checks that an edit is refused, closes the event, issues batches, scores and finalizes every assignment, checks that peer scores are 403, publishes, reads the results as a stranger, and checks that a late finalize is 409. It prints every request and ends `lifecycle PASS` (78 requests, about 30 seconds).

**5. The tests.** `docker compose --profile test run --rm test` runs pytest inside the image against the compose Postgres. See [Tests](#tests).

## Receipts

Every file below is the output of a command, not typed. CI ([`.github/workflows/acceptance.yml`](.github/workflows/acceptance.yml)) writes them with `tools/verify.py` (standard library only). After a green run, `python tools/verify.py fetch` copies them from it with `gh run download` and writes [`receipts/ci-run.txt`](receipts/ci-run.txt), which names the run, the commit and each job's conclusion. `fetch` refuses a run that is not green, a run whose amd64 and arm64 reports differ, and a run that tested code other than this checkout's (only the receipts and the top-level `*.md` files may have changed since).

- [`acceptance-report.txt`](acceptance-report.txt): `python tools/verify.py stack` against a cold `docker compose up` on amd64 (arm64 gives the same bytes). It runs `run.py .dogfood.toml`, then the tests and the oracle below, then `run.py` again, and fails unless both reports are `claimed T1 T2, verified T1 T2` and identical.
- [`receipts/tests.txt`](receipts/tests.txt): `docker compose --profile test run --rm test`, from the same step.
- [`receipts/oracle-statsmodels.txt`](receipts/oracle-statsmodels.txt): `docker compose --profile oracle run --rm oracle`, from the same step.
- [`receipts/backup-restore.txt`](receipts/backup-restore.txt): `python tools/verify.py backup` on that stack: the documented backup command, a change (the Dry Harbour duplicate is merged), the documented restore command. It fails unless `scores.csv`, the audit log length, the audit chain and the duplicate decision are back to what they were at the backup, and `run.py` still passes.
- [`receipts/production-refusal-demo-db.txt`](receipts/production-refusal-demo-db.txt), [`receipts/production-mode.txt`](receipts/production-mode.txt), [`receipts/production-lifecycle.txt`](receipts/production-lifecycle.txt), [`receipts/readiness-db-down.txt`](receipts/readiness-db-down.txt): `python tools/verify.py production`, with random secrets. Production mode refuses a volume first seeded in demo mode and leaves `samepage_app` untouched; on a fresh volume it boots, `/demo/enter/org` is 404 and the demo organizer token is 401; `manage.py samepage_admin` makes the first admin and `tools/lifecycle_check.py` runs one event from creation to published results (one-time link secrets are cut to their first characters); with the database container stopped, `/healthz` is 200, `/readyz.json` 503 problem+json and an API URL 500 problem+json.
- [`receipts/inputs.txt`](receipts/inputs.txt): sha256 of `run.py` and `fixtures.json` (`python tools/verify.py inputs`, also run by `fetch`), which are byte-identical to the organizers' files.

## What that proves

| Proves | Does not prove |
|---|---|
| Refusal lives in the backend and covers HTML, JSON and CSV. A judge asking for another judge's scores gets 403, not an empty page. | That a database superuser cannot edit a row. The audit chain and a downloaded CSV detect that afterwards. Nothing is signed. |
| The REML fit is the GLS estimator at the λ that maximises the profile likelihood on a fixed grid. statsmodels, an independent implementation, gets the same λ and ranking. A dense inverse agrees with the Woodbury form to about 1e-15 on the seed (the test asserts 1e-9). | That the model suits this data. The project signal is small: the results page says the top 5 is a statistical tie across ranks 1 to 15. |
| The progress numbers equal the row counts of the CSVs they link to, checked on every request. | Anything about T3 or T4. We do not claim them. |

## Limits

Known gaps, not hidden:

- **Nothing is emailed.** Team invite links, set-password links and role acceptance links are shown once, to the person who created them, to pass on by hand. There is no self-service password reset: an operator runs `python manage.py changepassword <email>`.
- **HTTPS behind a proxy is not ready.** With a reverse proxy that terminates TLS and forwards plain HTTP, Django sees `http` while the browser sends `Origin: https://…`, so every browser form post, sign-in included, fails the CSRF check with 403. There is no `SECURE_PROXY_SSL_HEADER` or `CSRF_TRUSTED_ORIGINS` setting yet. Plain HTTP (demo mode, CI) works.
- **No API tokens outside demo mode.** Bearer tokens are only the seeded demo ones. A script against a production instance signs in with `POST /login` and sends the session cookie and CSRF token, as `tools/lifecycle_check.py` does.
- **Bulk import/export.** Full event bundles are imported via `POST /e/import.json` (admin only) and exported via `GET /e/<event>/export.json`.
- **Conflicts of interest are partly manual.** The matcher and manual assignment exclude a judge whose email is on the team, and any row in the `coi` table, but no page or route writes that table: an operator adds a declared conflict with SQL. Likewise a per-submission `deadline_exception` row is honoured by the triggers but has no route.
- **Deletion.** Tracks, prize categories and events cannot be deleted, only added; event states only move forward. An issued assignment cannot be withdrawn, only its batch abandoned (its unfinished work is then topped up to other judges). There is no retention or account deletion tooling; an operator deletes rows with SQL.
- **The public gallery shows every track to everyone, judges included.** Track scoping applies to judging: a judge is assigned, opens in the console and scores only projects in their tracks, and reads only their own scores.
- **Small events fall back to plain means.** When no project has reviews that disagree, the judge-bias model cannot be fitted; results then rank by the mean weighted total with no judge adjustment, and the results page says so ([JUDGING.md](JUDGING.md#when-the-model-cannot-be-fitted)).
- **Uploads.** Images are stored as uploaded (2 MB each, no resizing, no metadata stripping, no virus scan); the type is sniffed from the bytes and served with a sandboxing CSP.
- **Open sign-up.** Anyone who can reach the portal can create an account (throttled, CSRF-checked). There is no captcha and no email verification.
- **Lab tie-breaks.** Raw and k=10 ranks in the lab break exact ties by float noise rather than by the documented submission-time rule.
- **Isolation is application code.** Read isolation is one policy module, not Postgres row-level security. The runtime database role cannot update `score_rev` or the audit log and does not own the tables, so it cannot disable those triggers, but the owner password is in the app container for migrations, and a host operator can edit rows. A downloaded CSV is the witness.

## Layout

Django 5.2, Django REST Framework, Postgres 16, gunicorn, WhiteNoise, Pico CSS (vendored, MIT, see [NOTICE](NOTICE)) and one small `console.js` for autosave and keyboard scoring. NumPy is the only maths library in the runtime image; statsmodels lives only in the separate oracle image.

`samepage/domain/` and `samepage/engine/` import no Django (`.importlinter`, checked in CI). Views call services; services are the only writers. The details are in [ARCHITECTURE.md](ARCHITECTURE.md), [DATA-MODEL.md](DATA-MODEL.md), [JUDGING.md](JUDGING.md), [THREAT_MODEL.md](THREAT_MODEL.md), [OPERATIONS.md](OPERATIONS.md), [DECISIONS.md](DECISIONS.md) and [PRIVACY.md](PRIVACY.md).

## Tests

```
docker compose --profile test run --rm test
```

Natively, with Python 3.12 and a Postgres role that may create a database (pytest-django creates and drops `test_<name>`):

```
pip install -r requirements-dev.txt
DATABASE_URL=postgres://owner:password@127.0.0.1:5432/samepage python -m pytest
```

Without `DATABASE_URL` only the pure tests (policy tables, REML, rules) run; the database tests are skipped and say so. `tests/test_authz_matrix.py` sends every route to seven principals in every format; `tests/test_lifecycle.py` (T1), `tests/test_judging_flow.py` (T2) and `tests/test_e2e_browser.py` (one event through the HTML forms with CSRF enforced) drive the flows through the URLs a browser uses. The last CI run is [receipts/tests.txt](receipts/tests.txt).

## License

Apache License 2.0 ([LICENSE](LICENSE)). Pico CSS is MIT ([NOTICE](NOTICE)).
