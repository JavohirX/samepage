"""Deterministic demo bearer tokens. HMAC so a reseed does not rotate them."""

from __future__ import annotations

import hashlib
import hmac

DEMO_SECRET = "samepage-demo-secret-v1"
DEMO_PASSWORD = "samepage-demo"

PRINCIPALS = {
    "org": {"id": "org_01", "email": "organizer@example.org", "name": "Organizer", "role": "organizer"},
    "admin": {"id": "adm_01", "email": "admin@example.org", "name": "Admin", "role": "admin"},
    "jdg08": {"id": "jdg_08", "email": "marek.nowak@example.org", "name": "Marek Nowak", "role": "judge"},
    "jdg03": {"id": "jdg_03", "email": "priya.nair@example.org", "name": "Priya Nair", "role": "judge"},
    "priya1": {"id": "per_priya1", "email": "priya1@example.org", "name": "Priya", "role": "participant"},
    "control": {"id": "per_control", "email": "control@example.org", "name": "Control", "role": "participant"},
}


def demo_token(slug: str) -> str:
    mac = hmac.new(DEMO_SECRET.encode(), slug.encode(), hashlib.sha256).hexdigest()
    return f"sp_demo_{slug}_{mac}"


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
