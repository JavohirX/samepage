"""Canonical JSON for the audit chain. Payloads are strings, ints, lists and objects."""

from __future__ import annotations

import json


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def ranking_sha256(lines: list[tuple[str, int]]) -> str:
    import hashlib

    body = "".join(f"{project_id},{rank}\n" for project_id, rank in lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
