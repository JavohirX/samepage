# Security

Report a problem by opening an issue with the route, the role, and the response status. Do not include a live token from a real event.

Demo tokens in this repository are fixtures. They only work when `SAMEPAGE_MODE=demo`.

The threat model is THREAT_MODEL.md. Isolation is enforced in `samepage/core/policy.py` and `samepage/services/access.py`, before a view loads the target row.
