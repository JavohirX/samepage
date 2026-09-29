# Security

Report a problem by opening an issue with the route, the role, and the response status. Do not include a live token from a real event.

The bearer tokens in `.dogfood.toml` and the password `samepage-demo` are public fixtures. They work only when `SAMEPAGE_MODE=demo`: production mode answers 401 to a demo token, never accepts the demo password, and refuses to start while either is still in its database (`samepage/ops/preflight.py`, `tests/test_production.py`).

The threat model is THREAT_MODEL.md; what is not mitigated is listed there and under Limits in README.md. Isolation is enforced in `samepage/core/policy.py` and `samepage/services/access.py`, before a view loads the target row.
