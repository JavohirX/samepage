# Samepage

Every number on a page opens as the rows behind it. Each list is also a CSV file and a JSON file. HTML, JSON and CSV come from the same rows, through the same policy check, so a tool we did not write can audit them: the organizers' `run.py`, and a statsmodels container that re-derives the ranking from `scores.csv`.

```
pitch = "Every number on every page opens as the rows behind it: each list page is also a CSV and a JSON file from one policy check, and statsmodels re-derives our normalized ranking from the scores.csv an organizer downloads."
```

Claimed tiers: **T1 and T2**. T3 is not built. T4 is not claimed. `run.py` on this repo prints `claimed T1 T2, verified T1 T2`.

## Run it

The first build needs the network, once, to pull images. After that the stack runs with the network off.

```
docker compose up --wait
python run.py .dogfood.toml
```

On Windows use `python`, and `curl.exe` rather than PowerShell's `curl` alias. The checker is stdlib only. `fixtures.json` sits next to `run.py`.

Demo sign-in, printed again when the container boots. The password for all six demo accounts is `samepage-demo`.

| Who | Link | Email |
|---|---|---|
| Organizer | http://localhost:8080/demo/enter/org | organizer@example.org |
| Judge A (jdg_08) | http://localhost:8080/demo/enter/jdg08 | marek.nowak@example.org |
| Judge B (jdg_03) | http://localhost:8080/demo/enter/jdg03 | priya.nair@example.org |
| Participant | http://localhost:8080/demo/enter/priya1 | priya1@example.org |

Those links exist only in demo mode. Production refuses to boot while a demo token is present (`python tools/task.py` is the local runner; production checks are in OPERATIONS.md).

## The check a judge can do

**1. The organizers' checker.** `python run.py .dogfood.toml`. Last line: `claimed T1 T2, verified T1 T2`.

**2. A number opens as its rows.** Sign in as the organizer and open `/e/evt_01/progress`. The sentence is "121 counted + 5 excluded = 126". The "5 excluded" link is `scores.csv?counted=false`: five rows, all `prj_07`, each `withdrawn_duplicate:dup_01`. The footer says "6 of 6 numbers on this page match their CSV".

```
curl.exe -s -H "Authorization: Bearer <organizer token from .dogfood.toml>" http://localhost:8080/e/evt_01/scores.csv
```

The file has 126 data rows. 121 have `counted=true`.

**3. The ranking is re-derived, not asserted.** `/e/evt_01/results` (organizer, before publish) shows raw mean, REML-adjusted and Raptors k=10 on one row. On the deduplicated fixture the engine's λ is 15.324. The top 5 are prj_34, prj_11, prj_25, prj_10 and prj_37, the same set as the raw top 5. Dry Harbour (prj_41) is rank 9 under keep-latest. The duplicates page also prints the merge alternative, which counts prj_07's reviews toward prj_41, including three judges twice.

`docker compose --profile oracle run --rm oracle` is the outside check: it downloads `scores.csv` and evaluates statsmodels' REML likelihood on the grid in JUDGING.md. The grid is ours. The likelihood is theirs. The check that runs in this tree without that image is the dense inverse of the same model, which matches the Woodbury fit to 1e-9 (`tests/domain/test_reml.py`).

## What that proves

| Proves | Does not prove |
|---|---|
| Refusal lives in the backend and covers HTML, JSON and CSV. `run.py` is 7/7. A judge asking for another judge's scores gets 403, not an empty page. | That a database superuser cannot edit a row. The audit chain and a downloaded CSV detect that afterwards. Nothing is signed. |
| The REML fit is the GLS estimator at the λ that maximises the profile likelihood on a fixed grid. A dense inverse agrees to 1e-9. | That the model suits this data. The project signal is tiny. The results page says the top 5 is a statistical tie. |
| Every list the organizer sees is the same rows as its CSV. | Anything about T3 or T4. `run.py` does not check them, and we do not claim them. |

## What a visitor, a judge and an organizer actually do

The gallery at `/e/evt_01/projects` is public, server-rendered, in fixture order. Glass Signal, Small Meadow and Deep Compass are on page one. Search and track filters are the same rows in HTML, JSON and CSV. A logged-out request is never redirected: a protected page returns 401 with the sign-in form inline, and a JSON client gets problem+json.

A participant can draft and submit until the deadline. On this fixture the deadline is already past, so `POST /e/evt_01/projects.json` returns 409 with `submissions closed at 2026-03-01T18:00:00Z` before the body is validated. The same POST to the open control event `/e/evt_02/projects.json` returns 201. A database trigger repeats the deadline rule.

A judge scores in `/e/evt_01/judge/batches`. Keys 1–5 set a score, J and K move between criteria, and the page autosaves. The buttons work with JavaScript off. Their own scores are `/e/evt_01/judges/me/scores`. Another judge's URL returns 403 before the id is loaded, so a missing judge is also 403 rather than 404. Participants get 403 on that route too.

An organizer sees progress with every count linked to the filtered CSV, confirms or changes the Dry Harbour decision, reads the normalization lab (raw, z, REML, k=10, the z-score failures, λ sensitivity, leave-one-judge-out), and publishes. Publishing returns 409 until `dup_01` is confirmed. Before publish, anonymous results are 403 with `Cache-Control: private, no-store`. After publish they are public.

`/about/access` is generated from the same policy tables the server enforces.

## Limits

- T3 is not built. No community voting, comments or quadratic voting.
- No webhooks, certificates, signed judge records or embeddable widget.
- No OpenAPI file. The JSON and CSV twins exist; "API First" is not claimed.
- Read isolation is one policy module in application code, not Postgres row-level security.
- The runtime database role cannot update `score_rev` or the audit log and does not own the tables, so it cannot disable those triggers. The owner password is still in the app container for migrations. A host operator can edit rows. A downloaded CSV is the witness.
- The statsmodels default fit is a bad guide on this likelihood, which is why the grid is part of the method. See JUDGING.md.
- Demo bearer tokens are deterministic and printed at boot. They are refused in production mode.
- Not tested here as a published multi-arch image. `docker compose up` is the path a judge runs. Local development against Postgres uses `DATABASE_URL`.

## Layout

Django 5.2, Django REST Framework, Postgres 16, gunicorn, WhiteNoise, Pico CSS (vendored) and a small `console.js`. Numpy is the only maths library in the runtime image. The oracle image is separate and holds statsmodels, pandas and scipy.

`samepage/domain/` has no Django imports. `samepage/engine/` is the REML fit, z-scores and the assignment matcher. Views call services. Services are the writers.

Planning notes from before kickoff are in `plan/`. They are not the product.

## Tests

```
python -m pytest tests/domain tests/test_policy.py
```

The REML test refits `fixtures.json` and checks λ, the top-5 set, Dry Harbour at rank 9, and the eight short projects.
