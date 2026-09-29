# Reviewing Samepage

A rubric-to-evidence map for evaluators. Every claim links to the file or command that proves it.

## Tier Completion & Correctness (40%)

| Claim | Evidence | Command |
|---|---|---|
| T1 gallery is public | `samepage/core/policy.py` `ACTION_POLICY["gallery.read"]` → `EVERYONE` | `curl http://localhost:8080/e/evt_01/projects` (no auth, 200) |
| T1 deadline enforced server-side | `samepage/apps/portal/migrations/` SQL triggers + `samepage/services/submissions.py` | `run.py` check 3 (PASS) |
| T2 judge sees own scores | `samepage/core/policy.py` `ACTION_POLICY["scores.read_own"]` → `{JUDGE}` | `run.py` check 4 (PASS) |
| T2 judge cannot see peer scores | `samepage/services/access.py` → 403 before id resolution (D11) | `run.py` checks 5-6 (PASS); `curl -H "Authorization: Bearer <judge_b>" .../judges/jdg_08/scores` → 403 |
| T2 CSV export | One URL, three formats through `samepage/core/views.py` | `run.py` check 7 (PASS) |
| T1+T2 verified 7/7 | [acceptance-report.txt](acceptance-report.txt) | `python run.py .dogfood.toml` |
| CI green on amd64 + arm64 | [receipts/ci-run.txt](receipts/ci-run.txt), 5 green jobs | [GitHub Actions](https://github.com/JavohirX/samepage/actions) |
| T3 and T4 not claimed | `.dogfood.toml` line 5: `claimed = ["T1", "T2"]` | Built and tested, not claimed; table and tests in README "T3 and T4", known gaps under README Limits |

## Judging Integrity (25%)

| Claim | Evidence | How to verify |
|---|---|---|
| Backend role isolation | `samepage/core/policy.py`: one policy table, checked before target row is loaded | `tests/test_authz_matrix.py`: every route × 7 principals × 3 formats |
| 403 before resolving forbidden id | `samepage/services/access.py` calls `policy.allows` before any query | Try `curl -H "Authorization: Bearer <judge_b>" .../judges/jdg_08/scores.json` → 403 (not 404) |
| Least-privilege DB role | `samepage/ops/roles.py` `ensure_app_role` (REVOKE UPDATE, DELETE on `score_rev` and `audit_event`) and `runtime_self_check` (refuses to serve otherwise), called from `samepage/ops/entrypoint.py` | `psql -U samepage_app -c "UPDATE score_rev ..."` → permission denied (README showcase 4) |
| Defensible normalization | `samepage/engine/reml.py` (Woodbury REML), cross-checked by `tools/oracle_statsmodels.py` | `docker compose --profile oracle run --rm oracle` → λ and ranking match (README showcase 2) |
| Audit trail | `samepage/services/audit.py`, append-only `audit_event` table (trigger in `migrations/0002_triggers.py`), hash chain | `curl -H "Authorization: Bearer <organizer>" localhost:8080/e/evt_01/audit.json`: `chain_ok` and the first break are in the JSON (the HTML audit page lists the events only). The chain head is not anchored outside the database; a kept `audit.csv` is the witness. |
| Results before publish | 403 to everyone but organizers, anonymous included (a stranger gets 401 on the other staff routes) | `tests/test_authz_matrix.py` rows for `/e/evt_01/results` |
| The judge who marks everything the same | jdg_07 gave 4/4/4 to every project: kept in the fit, flagged `straight_line`, its z-score refused by name ([JUDGING.md](JUDGING.md)) | Organizer → `/e/evt_01/normalization` |
| Numbers agree across dashboard, CSV and results | The progress page renders each linked CSV and compares row counts on every request (`samepage/services/ledger.py`) | `/e/evt_01/progress` as Organizer: "6 of 6 numbers on this page match…" (README showcase 3) |
| CSV formula injection | `samepage/domain/csvguard.py`: text cells starting with `= + - @`, tab or CR get a leading quote | `tests/test_writes.py`, `tests/test_judging_flow.py` |
| XSS | Django autoescaping, and `Content-Security-Policy: default-src 'self'` on every response (`samepage/core/headers.py`) | `curl -sI localhost:8080/` |
| Dry Harbour duplicate | prj_07/prj_41 in fixtures, handled as keep-latest with provisional/confirmed states | Progress page shows 5 excluded rows, all prj_07 |

## Adoptability & Operability (20%)

| Claim | Evidence | How to verify |
|---|---|---|
| One-command start | `docker compose up --wait` | Run it cold |
| Seeded demo data | `samepage/services/seed.py` loads `fixtures.json` in demo mode | Open http://localhost:8080 after `docker compose up` |
| Demo bar role switching | `samepage/templates/` demo bar with POST + CSRF | Click buttons at the top of any page |
| Import/export | `samepage/services/bundle.py`, `tests/test_bundle.py` | `GET /e/evt_01/export.json`, `POST /e/import.json` |
| Backup/restore | [OPERATIONS.md](OPERATIONS.md#backup), CI-tested | [receipts/backup-restore.txt](receipts/backup-restore.txt) |
| Production mode | Refuses demo creds, requires strong secrets | [receipts/production-mode.txt](receipts/production-mode.txt), [receipts/production-lifecycle.txt](receipts/production-lifecycle.txt) |
| Offline boot | CI boots with container egress blocked | [receipts/ci-run.txt](receipts/ci-run.txt): "boot with container egress blocked: success" |

## Code Quality & Innovation (15%)

| Claim | Evidence | How to verify |
|---|---|---|
| Domain layer imports no Django | `samepage/domain/` + `.importlinter` | `lint-imports` (CI checks it) |
| Engine imports only NumPy | `samepage/engine/` + `.importlinter` | Same contract |
| One URL, three formats | `samepage/core/views.py` `SamepageView`, `samepage/core/renderers.py` | Append `.json` or `.csv` to any list URL |
| Exact-fraction weighted totals | `samepage/domain/weighted.py` (Python `fractions.Fraction`) | `tests/domain/test_rules.py::test_weighted_total_is_exact` |
| statsmodels cross-check | `tools/oracle_statsmodels.py` fits its own MixedLM | [receipts/oracle-statsmodels.txt](receipts/oracle-statsmodels.txt) |

## Out-of-scope traps

| Trap | Our answer | Where |
|---|---|---|
| Frontend-only auth | No. Policy checked in `samepage/services/access.py` before any row is loaded. | `tests/test_authz_matrix.py` |
| Mock/fake auth | No. Real PBKDF2 hashes, real CSRF, real session cookies. Bearer tokens only in demo mode. | `samepage/services/accounts.py`, `SECURITY.md` |
| Hardcoded features | No. Fixtures are loaded by `seed.py` in demo mode only. | `.dogfood.toml`, `samepage/services/seed.py` |
| No OSI license | Apache 2.0 full text in [LICENSE](LICENSE). | `LICENSE` |
| Cloud dependencies | None. Postgres is the only external service. | `docker-compose.yml`, `requirements.txt` |
