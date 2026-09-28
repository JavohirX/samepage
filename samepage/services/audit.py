"""Hash-chained audit log. Appends take an advisory lock so the chain has one writer."""

from __future__ import annotations

import hashlib

from django.db import connection, transaction

from samepage.apps.portal.models import AuditEvent
from samepage.domain.canonical import canonical

GENESIS = "0" * 64


def append(event_id: str, actor: str, action: str, object_ref: str, before, after) -> int:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [event_id])
        previous = (
            AuditEvent.objects.filter(event_id=event_id).order_by("-seq").values_list("hash", flat=True).first()
        )
        prev_hash = previous or GENESIS
        payload = {
            "actor": actor,
            "action": action,
            "object": object_ref,
            "before": before,
            "after": after,
            "prev": prev_hash,
        }
        digest = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
        row = AuditEvent.objects.create(
            event_id=event_id,
            actor=actor,
            action=action,
            object_ref=object_ref,
            before=before,
            after=after,
            prev_hash=prev_hash,
            hash=digest,
        )
        return row.seq


def verify(event_id: str) -> dict:
    rows = list(AuditEvent.objects.filter(event_id=event_id).order_by("seq"))
    prev = GENESIS
    for row in rows:
        payload = {
            "actor": row.actor,
            "action": row.action,
            "object": row.object_ref,
            "before": row.before,
            "after": row.after,
            "prev": prev,
        }
        digest = hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()
        if row.prev_hash != prev or row.hash != digest:
            return {
                "ok": False,
                "broken_seq": row.seq,
                "detail": f"chain breaks at seq {row.seq} ({row.action} {row.object_ref})",
            }
        prev = row.hash
    return {"ok": True, "head": prev, "rows": len(rows), "broken_seq": None, "detail": f"{len(rows)} events, chain intact"}
