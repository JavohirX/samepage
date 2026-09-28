# Contributing

Before sending a change:

```
DATABASE_URL=postgres://owner:password@127.0.0.1:5432/samepage python -m pytest
lint-imports
```

If you touch a route, also run `python run.py .dogfood.toml` against a booted stack. CI (`.github/workflows/acceptance.yml`) runs all of this on `docker compose up` for amd64 and arm64, plus the statsmodels oracle and the production-mode refusals.

Do not add a second way to render a list. Add the rows to the service that already feeds HTML, JSON and CSV.

Do not put a test-only switch in the runtime image. Tests change settings through pytest-django's `settings` fixture.

T3 stays out unless the README's tier line is updated in the same change and the claim stays honest about what `run.py` can see.
