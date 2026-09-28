# Contributing

Before sending a change:

```
DATABASE_URL=postgres://owner:password@127.0.0.1:5432/samepage python -m pytest
lint-imports
```

If you touch a route, also run `python run.py .dogfood.toml` against a booted stack. CI (`.github/workflows/acceptance.yml`) runs all of this on `docker compose up` for amd64 and arm64 through `tools/verify.py`: `stack` (the checker, the tests in the image, the statsmodels oracle, the checker again), `backup` (backup, a change, restore) and `production` (the refusals, one event over HTTP, readiness with the database down). Each step exits 1 on the first check that fails and says which.

Do not edit a receipt by hand. Once CI is green on your commit, `python tools/verify.py fetch` (needs `gh`) copies the receipts from that run into `acceptance-report.txt` and `receipts/`, and names the run in `receipts/ci-run.txt`; commit them as they are.

Do not add a second way to render a list. Add the rows to the service that already feeds HTML, JSON and CSV.

Do not put a test-only switch in the runtime image. Tests change settings through pytest-django's `settings` fixture.

T3 stays out unless the README's tier line is updated in the same change and the claim stays honest about what `run.py` can see.
