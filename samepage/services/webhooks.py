"""Webhooks service: Standard Webhooks outbox, SSRF guard, and delivery (S12)."""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any
import urllib.request
import urllib.error

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from samepage.apps.portal.models import AuditEvent, Event, WebhookDelivery, WebhookEndpoint
from samepage.core.errors import Unprocessable
from samepage.domain import webhooks
from samepage.services import audit


def register_endpoint(event: Event, url: str, secret: str = "", actor: str = "admin") -> WebhookEndpoint:
    """Register a new webhook endpoint for an event after SSRF validation."""
    allow_local = getattr(settings, "ALLOW_LOCAL_WEBHOOKS", False)
    is_safe, err = webhooks.is_ssrf_safe_url(url, allow_local=allow_local)
    if not is_safe:
        raise Unprocessable(f"Invalid webhook URL: {err}")

    if not secret:
        # Standard Webhooks format: whsec_ followed by base64 key
        raw_key = secrets.token_bytes(24)
        secret = "whsec_" + base64.b64encode(raw_key).decode("ascii")

    endpoint = WebhookEndpoint.objects.create(
        id=f"whep_{secrets.token_hex(8)}",
        event=event,
        url=url,
        secret=secret,
        is_active=True,
        created_at=timezone.now(),
    )
    audit.append(
        event.id,
        actor,
        "webhook.endpoint.create",
        f"event/{event.id}/webhooks/{endpoint.id}",
        {},
        {"url": url, "endpoint_id": endpoint.id},
    )
    return endpoint


def enqueue_event(event: Event, event_type: str, payload: dict[str, Any]) -> list[WebhookDelivery]:
    """Enqueue an event to the delivery outbox for all active endpoints."""
    endpoints = list(WebhookEndpoint.objects.filter(event=event, is_active=True))
    if not endpoints:
        return []

    timestamp = int(time.time())
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    deliveries = []

    with transaction.atomic():
        for ep in endpoints:
            msg_id = f"msg_{secrets.token_hex(12)}"
            signature = webhooks.generate_webhook_signature(ep.secret, msg_id, timestamp, payload_json)
            deliv = WebhookDelivery.objects.create(
                id=f"whdel_{secrets.token_hex(10)}",
                event=event,
                endpoint=ep,
                event_type=event_type,
                msg_id=msg_id,
                timestamp=timestamp,
                payload=payload,
                signature=signature,
                status="pending",
                created_at=timezone.now(),
            )
            deliveries.append(deliv)

    return deliveries


def deliver_one(delivery: WebhookDelivery) -> bool:
    """Attempt single HTTP POST delivery of a webhook."""
    payload_json = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True)
    req = urllib.request.Request(
        delivery.endpoint.url,
        data=payload_json.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "webhook-id": delivery.msg_id,
            "webhook-timestamp": str(delivery.timestamp),
            "webhook-signature": delivery.signature,
            "User-Agent": "Samepage-Webhooks/1.0",
        },
        method="POST",
    )

    delivery.attempts += 1
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            delivery.response_code = response.status
            if 200 <= response.status < 300:
                delivery.status = "delivered"
                delivery.delivered_at = timezone.now()
                delivery.save(update_fields=["status", "attempts", "response_code", "delivered_at"])
                return True
            else:
                delivery.status = "failed"
                delivery.last_error = f"HTTP {response.status}"
                delivery.save(update_fields=["status", "attempts", "response_code", "last_error"])
                return False
    except urllib.error.HTTPError as exc:
        delivery.response_code = exc.code
        delivery.status = "failed"
        delivery.last_error = f"HTTPError {exc.code}"
        delivery.save(update_fields=["status", "attempts", "response_code", "last_error"])
        return False
    except Exception as exc:
        delivery.status = "failed"
        delivery.last_error = str(exc)
        delivery.save(update_fields=["status", "attempts", "last_error"])
        return False


def deliver_pending(limit: int = 50) -> int:
    """Deliver batch of pending outbox webhooks."""
    pending = list(
        WebhookDelivery.objects.filter(status="pending")
        .select_related("endpoint")
        .order_by("created_at")[:limit]
    )
    success = 0
    for d in pending:
        if deliver_one(d):
            success += 1
    return success


def get_event_feed(event: Event, after_seq: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    """Pollable event feed using event's cryptographic audit log (S12)."""
    events = (
        AuditEvent.objects.filter(event=event, seq__gt=after_seq)
        .order_by("seq")[:limit]
    )
    return [
        {
            "seq": e.seq,
            "event_id": e.event_id,
            "actor": e.actor,
            "action": e.action,
            "object": e.object_ref,
            "at": e.at.isoformat(),
            "before": e.before,
            "after": e.after,
            "hash": e.hash,
        }
        for e in events
    ]
