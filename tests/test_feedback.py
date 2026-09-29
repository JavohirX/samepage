"""Tests for distribution-first feedback packs and release gating (S9)."""

import pytest
from samepage.apps.portal.models import Event, Team
from samepage.domain import feedback
from samepage.services import feedback as fb_service

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_distribution_percentile_and_histogram():
    """Verify percentile calculation and ASCII histogram generation."""
    scores = [20.0, 40.0, 60.0, 80.0, 100.0]
    # Median is 60 -> exactly 50th percentile
    p_med = feedback.calculate_percentile(scores, 60.0)
    assert p_med == 50.0

    p_top = feedback.calculate_percentile(scores, 100.0)
    assert p_top == 90.0

    hist = feedback.generate_text_histogram(scores, team_score=60.0, num_bins=5)
    assert "YOUR SCORE" in hist
    assert "█" in hist


def test_feedback_pack_release_gating_and_idor(client, bearer):
    """Feedback is 403 until released; once released, teams can only view their own pack."""
    event = Event.objects.get(id="evt_01")
    # Temporarily set state to published to test feedback lifecycle
    event.state = "published"
    event.save(update_fields=["state"])

    # 1. Unreleased feedback returns 403 even to team members
    resp_unrel = client.get("/e/evt_01/teams/tm_01/feedback.json", **bearer("priya1"))
    assert resp_unrel.status_code == 403

    # 2. Organizer releases feedback
    resp_rel = client.post("/e/evt_01/feedback/release.json", {}, **bearer("org"))
    assert resp_rel.status_code == 200

    # 3. Team member on tm_01 (priya1) can now view feedback
    resp_priya = client.get("/e/evt_01/teams/tm_01/feedback.json", **bearer("priya1"))
    assert resp_priya.status_code == 200
    data = resp_priya.json()
    assert "overall_score" in data
    assert "percentile" in data
    assert "histogram" in data
    assert "criteria_means" in data

    # 4. Priya1 attempts IDOR on tm_02 (which she is not a member of) -> 403
    resp_idor = client.get("/e/evt_01/teams/tm_02/feedback.json", **bearer("priya1"))
    assert resp_idor.status_code == 403

    # 5. Organizer can view any team's feedback and export summary CSV
    resp_org = client.get("/e/evt_01/teams/tm_02/feedback.json", **bearer("org"))
    assert resp_org.status_code == 200

    resp_summary_csv = client.get("/e/evt_01/feedback.csv", **bearer("org"))
    assert resp_summary_csv.status_code == 200
    assert resp_summary_csv["Content-Type"].startswith("text/csv")
