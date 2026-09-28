# Samepage

A self-hosted hackathon submission and judging portal. Every number on a page opens as the rows behind it: each list is also a CSV file and a JSON file, built from the same rows through the same policy check. Tools we did not write can audit it: the organizers' `run.py`, and a separate statsmodels image that re-derives the published ranking from the `scores.csv` an organizer downloads.

Claimed tiers: **T1 and T2**. `run.py` prints `claimed T1 T2, verified T1 T2` (see `acceptance-report.txt`, produced by the CI run of `docker compose up`). Several tier bullets that `run.py` does not check are **not built yet**. The table below says which, in plain words.

| Tier bullet | State |
|---|---|
| T1 login, roles | Built. Password login (CSRF-checked, throttled), bearer tokens, per-event roles in one policy table. |
| T1 create an event | **Missing.** Events come from the seed. There is no create-event page or API. |
| T1 form a team | **Missing.** Teams come from the seed. The `invite` table exists but nothing writes it. |
| T1 submit a project | API only: `POST /e/<event>/projects.json`. There is no HTML submit form. |
| T1 edit until the deadline | **Missing.** No update route. The database trigger that refuses late edits exists. |
| T1 deadline stops submissions | Built, twice: the service returns 409 and a trigger refuses the insert. |
| T1 public gallery | Built. HTML, JSON and CSV, no login. |
| T2 invite and assign judges | Assign: dry-run and top-up runs (audited). Invite: **missing**. |
| T2 rubric the organizer can weight | Weights are stored and used with exact fractions, but **no page or API edits them**. |
| T2 judges cannot see each other's work | Built. 403 before the target id is loaded, in HTML, JSON and CSV. |
| T2 progress view | Built. Each number links to its CSV and is checked against it on every request. |
| T2 evening out harsh and generous judges | Built. Profile REML with a fixed grid, shown beside raw means and Raptors k=10 (JUDGING.md). |
| T2 CSV export | Built. Formula-guarded cells, no literal `null`. |

## Run it

```
docker compose up --wait
python run.py .dogfood.toml
```

The first build pulls the base images (pinned by digest, amd64 and arm64). After that nothing at runtime needs the network. The portal is on http://localhost:8080, published on 127.0.0.1 only. `fixtures.json` sits next to `run.py` and is also inside the image, where the boot seeds it.

On Windows use `python`, and `curl.exe` rather than PowerShell's `curl` alias. The checker is stdlib only. Running the app without Docker needs Python 3.12 and Postgres (OPERATIONS.md).

## Demo mode

`docker compose up` starts in demo mode (`SAMEPAGE_MODE=demo`). The boot log prints the four bearer headers in `.dogfood.toml`; they are HMACs of a fixed string, so they are the same on every fresh volume. Each page has a demo bar with one button per account. The button is a POST with a CSRF token, so a link or an image on another site cannot sign a browser in. The shared password is `samepage-demo`.

| Who | Account | Lands on |
|---|---|---|
| Organizer | organizer@example.org | `/e/evt_01/progress` |
| Judge A (jdg_08) | marek.nowak@example.org | `/e/evt_01/judge/batches` |
| Judge B (jdg_03) | priya.nair@example.org | `/e/evt_01/judge/batches` |
| Participant | priya1@example.org | `/e/evt_01/projects` |
| Participant on the open event | control@example.org | `/e/evt_02/projects` |
| Admin | admin@example.org | `/e/evt_01/progress` |

Everything in this section is public, so production mode refuses it. With `SAMEPAGE_MODE=production` (the default outside compose) the demo bar and `/demo/enter/*` are 404, demo bearer tokens get 401, the demo password never signs in, and the process refuses to start while demo tokens or demo passwords are in the database, or while the secret key, a database password or `ALLOWED_HOSTS=*` is a default (`samepage/ops/preflight.py`). CI proves both halves: a demo-seeded volume is refused, and a fresh production volume boots and answers 401 to the demo organizer token.

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

**4. The tests.** `docker compose --profile test run --rm test` runs pytest inside the image against the compose Postgres (HTTP role and format matrix, production refusals, CSRF on sign-in, write validation, the progress recount, the REML fit). CI also runs them natively.

## Receipts

Every file here is the output of a command, copied from the CI run named in `receipts/ci-run.txt` (`gh run view`), not typed:

- `acceptance-report.txt`: `python3 run.py .dogfood.toml` against a cold `docker compose up` on amd64 (arm64 gives the same bytes).
- `receipts/oracle-statsmodels.txt`: `docker compose --profile oracle run --rm oracle` against that stack.
- `receipts/production-refusal-demo-db.txt`: production mode started on a volume first seeded in demo mode, with real secrets. It refuses.
- `receipts/production-mode.txt`: production mode on a fresh volume: it boots, and the demo sign-in and the demo organizer token are refused.
- `receipts/readiness-db-down.txt`: the same stack with the database container stopped: `/healthz` 200, `/readyz.json` 503 problem+json, an API URL 500 problem+json.
- `receipts/inputs.txt`: sha256 of `run.py` and `fixtures.json` (`python tools/task.py inputs`), identical to the organizers' files.

## What that proves

| Proves | Does not prove |
|---|---|
| Refusal lives in the backend and covers HTML, JSON and CSV. A judge asking for another judge's scores gets 403, not an empty page. | That a database superuser cannot edit a row. The audit chain and a downloaded CSV detect that afterwards. Nothing is signed. |
| The REML fit is the GLS estimator at the λ that maximises the profile likelihood on a fixed grid. statsmodels, an independent implementation, gets the same λ and ranking. A dense inverse agrees with the Woodbury form to about 1e-15 (the test asserts 1e-9). | That the model suits this data. The project signal is tiny. The results page says the top 5 is a statistical tie. |
| The progress numbers equal the row counts of the CSVs they link to, checked on every request. | Anything about T3 or T4. We do not claim them. |

## Limits

Known gaps, not hidden:

- The T1 and T2 bullets marked missing in the table above.
- Draft (not yet finalized) scores are counted in the ledger and in the next results fit. The results snapshot is rebuilt only at seed time and when a duplicate decision is confirmed, so it can be stale after new scores, and nothing freezes the ranking after publish: a later duplicate switch or score changes what the public results page shows.
- The demo judges (jdg_08, jdg_03) have only imported, finalized scores, so their console has nothing to score until a top-up assigns them a project. Top-up picks judges pseudo-randomly and may not pick them.
- There is no unlock for a finalized score: a second finalize with different values is 409.
- T3 is not built. No webhooks, certificates, signed records, OpenAPI file or embeddable widget.
- Read isolation is one policy module in application code, not Postgres row-level security.
- The runtime database role cannot update `score_rev` or the audit log and does not own the tables, so it cannot disable those triggers. The owner password is still in the app container for migrations. A host operator can edit rows. A downloaded CSV is the witness.
- There is no way to bootstrap a real event without the Django shell or SQL: no admin, no create-event route, no import command.

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

Without `DATABASE_URL` only the pure tests (policy tables, REML, rules) run; the database tests are skipped and say so.

## License

Apache License 2.0 (LICENSE). Pico CSS is MIT (NOTICE).
