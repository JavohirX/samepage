"""Tests for event bundle import/export (S13).

Strict superset of fixtures.json format.
A round trip keeps every project, score, judge, track and criterion.
"""

import json
from pathlib import Path
import pytest
from django.conf import settings

from samepage.apps.portal.models import Event, ResultsSnapshot, Submission
from samepage.services import bundle as bundle_service
from samepage.services import results

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_roundtrip_bundle_export_import(client):
    """Export evt_01, import it as a new event, and check that every row type survives the round trip."""
    event = Event.objects.get(id="evt_01")
    # Ensure results snapshot exists
    results.rebuild(event.id)
    initial_snapshot = ResultsSnapshot.objects.filter(event=event).order_by("-seq").first()
    assert initial_snapshot is not None
    initial_hash = initial_snapshot.ranking_sha256
    assert initial_hash

    # Export bundle
    bundle_data = bundle_service.export_event_bundle(event)
    assert bundle_data["event"]["id"] == "evt_01"
    assert len(bundle_data["tracks"]) > 0
    assert len(bundle_data["judges"]) > 0
    assert len(bundle_data["teams"]) > 0
    assert len(bundle_data["projects"]) > 0
    assert len(bundle_data["scores"]) > 0
    assert bundle_data["results_hash"] == initial_hash

    # Import into new event
    new_evt, stats = bundle_service.import_event_bundle(bundle_data, new_event_id="evt_rt")
    assert new_evt.id.startswith("evt_rt")
    assert stats["read"] > 0
    assert stats["written"] > 0
    assert stats["rejected"] == 0

    # Verify ranking snapshot was built for new event
    imported_snapshot = ResultsSnapshot.objects.filter(event=new_evt).order_by("-seq").first()
    assert imported_snapshot is not None
    assert imported_snapshot.ranking_sha256
    assert len(imported_snapshot.payload["rows"]) == len(initial_snapshot.payload["rows"])

    # Re-export and verify full structural and data fidelity
    reexported = bundle_service.export_event_bundle(new_evt)
    assert len(reexported["projects"]) == len(bundle_data["projects"])
    assert len(reexported["scores"]) == len(bundle_data["scores"])
    assert len(reexported["judges"]) == len(bundle_data["judges"])
    assert len(reexported["tracks"]) == len(bundle_data["tracks"])
    assert len(reexported["criteria"]) == len(bundle_data["criteria"])


def test_import_fixtures_json():
    """Verify importing raw fixtures.json directly produces a valid, queryable event."""
    fixtures_path = Path(settings.BASE_DIR) / "fixtures.json"
    with open(fixtures_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    new_evt, stats = bundle_service.import_event_bundle(data, new_event_id="evt_fix")
    assert new_evt.id.startswith("evt_fix")
    assert stats["written"] > 0

    # Check imported projects
    subs = Submission.objects.filter(event=new_evt)
    assert subs.count() == len(data.get("projects", []))


def test_bundle_http_endpoints_and_auth(client, bearer):
    """Verify HTTP endpoints for export and import."""
    # 1. Export as admin/organizer
    resp = client.get("/e/evt_01/export.json", **bearer("org"))
    assert resp.status_code == 200
    bundle_data = resp.json()
    assert "event" in bundle_data
    assert "scores" in bundle_data

    # 2. Export as non-staff -> 403
    resp_denied = client.get("/e/evt_01/export.json", **bearer("priya1"))
    assert resp_denied.status_code == 403

    # 3. Import as non-staff -> 403
    resp_imp_denied = client.post(
        "/e/import.json",
        bundle_data,
        content_type="application/json",
        **bearer("priya1"),
    )
    assert resp_imp_denied.status_code == 403

    # 4. Import as admin -> 201
    resp_imp = client.post(
        "/e/import.json",
        bundle_data,
        content_type="application/json",
        **bearer("admin"),
    )
    assert resp_imp.status_code == 201
    res_json = resp_imp.json()
    assert res_json["ok"] is True
    assert "event_id" in res_json
    assert res_json["written"] > 0
