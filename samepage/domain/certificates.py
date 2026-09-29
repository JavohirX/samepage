"""Certificate generation and award derivation (S8).

Pure domain logic: self-contained SVG generation and rule-based award assignment.
Free of Django and web layers.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from xml.sax.saxutils import escape


def derive_awards(
    ranked_projects: list[dict[str, Any]],
    track_prizes: dict[str, str] | None = None,
    overall_prizes: list[str] | None = None,
    custom_overrides: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Derive awards by rule from published rankings.

    - Each prize tied to a track goes to that track's top project.
    - Overall prizes go to overall top places (1st, 2nd, 3rd...).
    - An organizer can override with an explicit decision.
    - Non-winning teams receive 'Certificate of Participation'.

    Returns: {project_id: {"award": str, "rank": int, "is_winner": bool}}
    """
    track_prizes = track_prizes or {}
    overall_prizes = overall_prizes or ["1st Place Overall", "2nd Place Overall", "3rd Place Overall"]
    custom_overrides = custom_overrides or {}

    results: dict[str, dict[str, Any]] = {}
    assigned_tracks: set[str] = set()

    for idx, p in enumerate(ranked_projects, start=1):
        pid = p["id"]
        track = p.get("track") or ""
        award = ""
        is_winner = False

        if pid in custom_overrides:
            award = custom_overrides[pid]
            is_winner = award.lower() != "participation"
        elif idx <= len(overall_prizes):
            award = overall_prizes[idx - 1]
            is_winner = True
        elif track and track in track_prizes and track not in assigned_tracks:
            award = track_prizes[track]
            assigned_tracks.add(track)
            is_winner = True
        else:
            award = "Certificate of Participation"
            is_winner = False

        results[pid] = {
            "award": award,
            "rank": idx,
            "is_winner": is_winner,
        }

    return results


def generate_certificate_svg(
    certificate_number: str,
    event_name: str,
    team_name: str,
    project_title: str,
    members: list[str],
    award_title: str,
    issued_date: str,
    verification_url: str,
    signature_base64: str,
    payload_sha256: str,
) -> str:
    """Generate a self-contained, print-ready SVG certificate (S8)."""
    esc_cert_no = escape(str(certificate_number))
    esc_event = escape(str(event_name))
    esc_team = escape(str(team_name))
    esc_proj = escape(str(project_title))
    esc_members = escape(", ".join(members) if members else "Team Members")
    esc_award = escape(str(award_title))
    esc_date = escape(str(issued_date))
    esc_url = escape(str(verification_url))
    esc_sig = escape(str(signature_base64[:48]) + "...") if signature_base64 else "unsigned"
    esc_sha = escape(str(payload_sha256))

    is_winner = "participation" not in award_title.lower()
    accent_color = "#e5a93b" if is_winner else "#4a69bd"
    border_color = "#d4af37" if is_winner else "#6a89cc"
    badge_title = "WINNER" if is_winner else "OFFICIAL ENTRY"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" width="1000" height="700">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#f8f9fa"/>
    </linearGradient>
    <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-opacity="0.15"/>
    </filter>
  </defs>

  <!-- Background -->
  <rect width="1000" height="700" fill="url(#bgGrad)"/>

  <!-- Ornate Border Frame -->
  <rect x="25" y="25" width="950" height="650" fill="none" stroke="{border_color}" stroke-width="4" rx="8"/>
  <rect x="35" y="35" width="930" height="630" fill="none" stroke="{accent_color}" stroke-width="1.5" stroke-dasharray="8 4" rx="6"/>

  <!-- Corner Ornaments -->
  <circle cx="50" cy="50" r="10" fill="{accent_color}" opacity="0.4"/>
  <circle cx="950" cy="50" r="10" fill="{accent_color}" opacity="0.4"/>
  <circle cx="50" cy="650" r="10" fill="{accent_color}" opacity="0.4"/>
  <circle cx="950" cy="650" r="10" fill="{accent_color}" opacity="0.4"/>

  <!-- Header -->
  <text x="500" y="90" font-family="'Helvetica Neue', Arial, sans-serif" font-size="14" font-weight="600" fill="{accent_color}" letter-spacing="4" text-anchor="middle">SAMEPAGE VERIFIED CREDENTIAL</text>
  <text x="500" y="145" font-family="'Georgia', serif" font-size="34" font-weight="bold" fill="#1e272e" text-anchor="middle">{esc_event}</text>

  <!-- Divider -->
  <line x1="350" y1="170" x2="650" y2="170" stroke="{accent_color}" stroke-width="2"/>

  <!-- Award Designation -->
  <text x="500" y="220" font-family="'Georgia', serif" font-size="28" font-style="italic" fill="#2f3542" text-anchor="middle">{esc_award}</text>

  <!-- Presented To -->
  <text x="500" y="270" font-family="'Helvetica Neue', Arial, sans-serif" font-size="13" font-weight="500" fill="#747d8c" letter-spacing="2" text-anchor="middle">PROUDLY PRESENTED TO</text>
  <text x="500" y="325" font-family="'Georgia', serif" font-size="36" font-weight="bold" fill="#1e272e" text-anchor="middle">{esc_team}</text>

  <!-- Project & Members -->
  <text x="500" y="375" font-family="'Helvetica Neue', Arial, sans-serif" font-size="18" fill="#57606f" text-anchor="middle">for the project: <tspan font-weight="bold" fill="#2f3542">"{esc_proj}"</tspan></text>
  <text x="500" y="415" font-family="'Helvetica Neue', Arial, sans-serif" font-size="15" fill="#747d8c" text-anchor="middle">Team Members: {esc_members}</text>

  <!-- Badge -->
  <g transform="translate(500, 480)">
    <circle r="36" fill="{accent_color}" opacity="0.15"/>
    <circle r="30" fill="none" stroke="{accent_color}" stroke-width="2"/>
    <text y="5" font-family="'Helvetica Neue', Arial, sans-serif" font-size="10" font-weight="bold" fill="{accent_color}" letter-spacing="1" text-anchor="middle">{badge_title}</text>
  </g>

  <!-- Footer Verification & Hash Block -->
  <g transform="translate(70, 560)">
    <!-- Certificate Meta -->
    <text x="0" y="20" font-family="monospace" font-size="11" fill="#57606f">Certificate No: <tspan font-weight="bold" fill="#2f3542">{esc_cert_no}</tspan></text>
    <text x="0" y="40" font-family="monospace" font-size="11" fill="#57606f">Issued Date:    {esc_date}</text>
    <text x="0" y="60" font-family="monospace" font-size="11" fill="#57606f">Payload SHA256: {esc_sha[:32]}...</text>
    <text x="0" y="80" font-family="monospace" font-size="11" fill="#57606f">Ed25519 Sig:    {esc_sig}</text>

    <!-- Verification URL -->
    <text x="860" y="20" font-family="monospace" font-size="11" fill="#57606f" text-anchor="end">Verify Authenticity at:</text>
    <text x="860" y="42" font-family="monospace" font-size="11" font-weight="bold" fill="{accent_color}" text-anchor="end">{esc_url}</text>
    <text x="860" y="64" font-family="'Helvetica Neue', Arial, sans-serif" font-size="10" fill="#a4b0be" text-anchor="end">Cryptographically signed with Ed25519</text>
  </g>
</svg>"""
    return svg
