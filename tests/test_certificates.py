"""Tests for certificate issuance, rule-based awards, SVG rendering, and verification (S8)."""

import pytest
from samepage.apps.portal.models import Event, Team, TeamCertificate
from samepage.domain import certificates
from samepage.services import certificates as cert_service

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_derive_awards_rules():
    """Verify rule-based award assignment: overall tops, track tops, participation."""
    projects = [
        {"id": "p1", "track": "trk_dev"},
        {"id": "p2", "track": "trk_ai"},
        {"id": "p3", "track": "trk_dev"},
        {"id": "p4", "track": "trk_other"},
        {"id": "p5", "track": "trk_sec"},
    ]
    track_prizes = {"trk_dev": "Best DevTool"}
    overall_prizes = ["1st Place Overall", "2nd Place Overall"]
    overrides = {"p5": "Special Jury Mention"}

    awards = certificates.derive_awards(
        projects,
        track_prizes=track_prizes,
        overall_prizes=overall_prizes,
        custom_overrides=overrides,
    )

    assert awards["p1"]["award"] == "1st Place Overall"
    assert awards["p1"]["is_winner"] is True
    assert awards["p2"]["award"] == "2nd Place Overall"
    assert awards["p2"]["is_winner"] is True
    # p3 is top dev remaining
    assert awards["p3"]["award"] == "Best DevTool"
    assert awards["p3"]["is_winner"] is True
    # p4 is non-winning
    assert awards["p4"]["award"] == "Certificate of Participation"
    assert awards["p4"]["is_winner"] is False
    # p5 has override
    assert awards["p5"]["award"] == "Special Jury Mention"


def test_certificate_issuance_and_http_endpoints(client):
    """Issue certificates for evt_01, verify SVG generation and verification endpoints."""
    event = Event.objects.get(id="evt_01")
    issued = cert_service.issue_certificates(event)
    assert len(issued) > 0

    first_cert = issued[0]
    team_id = first_cert.team_id
    cert_no = first_cert.certificate_number

    # Verify team certificate view
    resp = client.get(f"/e/evt_01/teams/{team_id}/certificate.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["certificate_number"] == cert_no
    assert "signature_ed25519" in data

    # Verify public SVG download endpoint
    resp_svg = client.get(f"/e/evt_01/teams/{team_id}/certificate.svg")
    assert resp_svg.status_code == 200
    assert resp_svg["Content-Type"].startswith("image/svg+xml")
    assert b"<svg" in resp_svg.content
    assert cert_no.encode("utf-8") in resp_svg.content

    # Verify public certificate lookup at /certificates/<cert_no>
    resp_lookup = client.get(f"/certificates/{cert_no}.json")
    assert resp_lookup.status_code == 200
    lookup_data = resp_lookup.json()
    assert lookup_data["valid"] is True
    assert lookup_data["team_id"] == team_id

    # Unknown certificate returns 404
    resp_404 = client.get("/certificates/CERT-NONEXISTENT.json")
    assert resp_404.status_code == 404
