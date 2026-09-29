# Reviewing Samepage

A rubric-to-evidence map for evaluators. Every claim links to the file or command that proves it.

## Tier Completion & Correctness (40%)

| Claim | Evidence | Command |
|---|---|---|
| T1 gallery is public | `samepage/core/policy.py` line 21: `gallery.read` → `EVERYONE` | `curl http://localhost:8080/e/evt_01/projects` (no auth, 200) |
| T1 deadline enforced server-side | `samepage/apps/portal/migrations/` SQL triggers + `samepage/services/submissions.py` | `run.py` check 3 (PASS) |
| T2 judge sees own scores | `samepage/core/policy.py` line 36: `scores.read_own` → `{JUDGE}` | `run.py` check 4 (PASS) |
| T2 judge cannot see peer scores | `samepage/services/access.py` → 403 before id resolution (D11) | `run.py` checks 5-6 (PASS); `curl -H "Authorization: Bearer <judge_b>" .../judges/jdg_08/scores` → 403 |
| T2 CSV export | One URL, three formats through `samepage/core/views.py` | `run.py` check 7 (PASS) |
| T1+T2 verified 7/7 | [acceptance-report.txt](acceptance-report.txt) | `python run.py .dogfood.toml` |
| CI green on amd64 + arm64 | [receipts/ci-run.txt](receipts/ci-run.txt), 5 green jobs | [GitHub Actions](https://github.com/JavohirX/samepage/actions) |
| T3 not claimed | `.dogfood.toml` line 5: `claimed = ["T1", "T2"]` | Built and tested but not claimed |
| T4 not claimed | `.dogfood.toml` line 5 | Built and tested but not claimed |

## Judging Integrity (25%)

| Claim | Evidence | How to verify |
|---|---|---|
| Backend role isolation | `samepage/core/policy.py`: one policy table, checked before target row is loaded | `tests/test_authz_matrix.py`: every route × 7 principals × 3 formats |
| 403 before resolving forbidden id | `samepage/services/access.py` calls `policy.allows` before any query | Try `curl -H "Authorization: Bearer <judge_b>" .../judges/jdg_08/scores.json` → 403 (not 404) |
| Least-privilege DB role | `samepage/ops/entrypoint.py`: creates `samepage_app`, grants read/write but not UPDATE on `score_rev` or audit | `receipts/production-mode.txt` |
| Defensible normalization | `samepage/engine/reml.py` (Woodbury REML), cross-checked by `tools/oracle_statsmodels.py` | `docker compose --profile oracle run --rm oracle` → λ and ranking match |
| Audit trail | `samepage/services/audit.py`, append-only `audit_event` table, chain hash | `curl -H "Authorization: Bearer <organizer>" .../audit.json` |
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
