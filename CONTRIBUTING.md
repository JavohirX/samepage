# Contributing

Run `python -m pytest tests/domain tests/test_policy.py` before sending a change. If you touch a route, run `python run.py .dogfood.toml` against a booted stack.

Do not add a second way to render a list. Add the rows to the service that already feeds HTML, JSON and CSV.

Do not put a test-only switch in the runtime image. A mutation of the policy tables belongs in the test process.

T3 stays out unless the README's tier line is updated in the same change and the claim stays honest about what `run.py` can see.
