"""Tests for Standard Webhooks, SSRF guard, outbox delivery, and event feed (S12)."""

import json
import pytest
from django.test import override_settings

from samepage.apps.portal.models import AuditEvent, Event, WebhookDelivery, WebhookEndpoint
from samepage.domain import webhooks
from samepage.services import webhooks as wh_service

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_standard_webhooks_signature_math():
    """Verify Standard Webhooks signature formatting and verification."""
    secret = "whsec_MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE"
    msg_id = "msg_test123"
    ts = 1700000000
    payload = json.dumps({"event": "ping"}, separators=(",", ":"))

    sig_header = webhooks.generate_webhook_signature(secret, msg_id, ts, payload)
    assert sig_header.startswith("v1,")

    # Verify signature
    assert webhooks.verify_webhook_signature(secret, msg_id, ts, payload, sig_header, current_time=ts) is True
    # Tampered payload fails
    assert webhooks.verify_webhook_signature(secret, msg_id, ts, "tampered", sig_header, current_time=ts) is False
    # Expired timestamp fails
    assert webhooks.verify_webhook_signature(secret, msg_id, ts, payload, sig_header, tolerance_seconds=60, current_time=ts + 100) is False


def test_ssrf_url_guard():
    """Verify SSRF validation blocks loopback, private IPs, and non-http schemes."""
    assert webhooks.is_ssrf_safe_url("http://127.0.0.1:8080/hook")[0] is False
    assert webhooks.is_ssrf_safe_url("http://localhost:3000/hook")[0] is False
    assert webhooks.is_ssrf_safe_url("http://192.168.1.1/hook")[0] is False
    assert webhooks.is_ssrf_safe_url("http://10.0.0.1/hook")[0] is False
    assert webhooks.is_ssrf_safe_url("ftp://example.com/hook")[0] is False
    assert webhooks.is_ssrf_safe_url("https://hooks.example.com/webhook")[0] is True


@override_settings(ALLOW_LOCAL_WEBHOOKS=True)
def test_webhooks_lifecycle_and_delivery(client, bearer):
    """Test webhook endpoint registration, event enqueuing, and delivery worker."""
    event = Event.objects.get(id="evt_01")

    # 1. Register endpoint
    resp_reg = client.post(
        "/e/evt_01/webhooks.json",
        {"url": "https://example.com/webhook", "secret": "whsec_testsecret123"},
        content_type="application/json",
        **bearer("org"),
    )
    assert resp_reg.status_code == 201
    ep_id = resp_reg.json()["id"]

    # 2. Enqueue event
    delivs = wh_service.enqueue_event(event, "results.published", {"event": "evt_01", "status": "published"})
    assert len(delivs) == 1
    d = delivs[0]
    assert d.status == "pending"
    assert d.signature.startswith("v1,")

    # 3. Test ping endpoint
    resp_test = client.post(f"/e/evt_01/webhooks/{ep_id}/test.json", {}, **bearer("org"))
    assert resp_test.status_code == 200

    # 4. Pollable event feed (/e/<e>/events.json?after=<seq>)
    resp_feed = client.get("/e/evt_01/events.json?after=0")
    assert resp_feed.status_code == 200
    feed_data = resp_feed.json()
    assert "items" in feed_data
    assert len(feed_data["items"]) > 0
    first_seq = feed_data["items"][0]["seq"]

    # Poll with after parameter
    resp_after = client.get(f"/e/evt_01/events.json?after={first_seq}")
    assert resp_after.status_code == 200
