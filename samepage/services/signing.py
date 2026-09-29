"""Signing service: RFC 9162 Merkle tree generation, root signing, and judge protocols (S7)."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    Event,
    JudgeProtocol,
    Person,
    ResultsSnapshot,
    ScoreCurrent,
    SignedRoot,
    Submission,
)
from samepage.domain import merkle
from samepage.services import audit

_KEY_CACHE: dict[str, tuple[Any, Any]] = {}


def get_signing_key(event_id: str = "") -> tuple[Any, Any]:
    """Retrieve or generate Ed25519 key pair for signing."""
    global _KEY_CACHE
    cache_key = event_id or "global"
    if cache_key in _KEY_CACHE:
        return _KEY_CACHE[cache_key]

    env_pem = os.environ.get("SAMEPAGE_SIGNING_KEY")
    if env_pem:
        priv = merkle.load_private_key_pem(env_pem.encode("utf-8"))
        pub = priv.public_key()
    else:
        priv, pub = merkle.generate_key_pair()

    _KEY_CACHE[cache_key] = (priv, pub)
    return priv, pub


def canonical_review_row(score: ScoreCurrent) -> bytes:
    """Format canonical review representation for Merkle leaf hashing."""
    return (
        f"REVIEW|{score.submission.event_id}|{score.judge_id}|"
        f"{score.submission_id}|{score.criterion}|{score.value}|"
        f"{score.comment.strip()}"
    ).encode("utf-8")


def generate_signed_records(event: Event) -> SignedRoot:
    """Generate Merkle tree over all counted reviews, sign root, and create judge protocols."""
    with transaction.atomic():
        # 1. Fetch latest snapshot sequence
        snapshot = ResultsSnapshot.objects.filter(event=event).order_by("-seq").first()
        pub_seq = snapshot.seq if snapshot else 1

        # Check if already exists for this seq
        existing = SignedRoot.objects.filter(event=event, publish_seq=pub_seq).first()
        if existing:
            return existing

        # 2. Gather counted review scores in deterministic order
        scores = list(
            ScoreCurrent.objects.filter(
                submission__event=event,
                state="final",
            )
            .select_related("judge", "submission")
            .order_by("submission_id", "judge_id", "criterion")
        )

        leaves: list[bytes] = []
        review_map: list[dict[str, Any]] = []

        for idx, s in enumerate(scores):
            canon_bytes = canonical_review_row(s)
            lh = merkle.leaf_hash(canon_bytes)
            leaves.append(lh)
            review_map.append({
                "index": idx,
                "score_id": f"{s.judge_id}:{s.submission_id}:{s.criterion}",
                "judge_id": s.judge_id,
                "submission_id": s.submission_id,
                "criterion_id": s.criterion,
                "score": int(s.value),
                "comment": s.comment,
                "canonical_row": canon_bytes.decode("utf-8"),
                "leaf_hash": lh.hex(),
            })

        # 3. Build Merkle tree & compute root
        root_bytes = merkle.compute_merkle_root(leaves) if leaves else hashlib.sha256(b"").digest()
        root_hex = root_bytes.hex()

        # 4. Prepare statement and sign with Ed25519
        ranking_sha = snapshot.ranking_sha256 if snapshot else ""
        statement = (
            f"SAMEPAGE PUBLISHED ROOT\n"
            f"Event: {event.id}\n"
            f"Publish-Seq: {pub_seq}\n"
            f"Ranking-SHA256: {ranking_sha}\n"
            f"Leaves: {len(leaves)}\n"
            f"Root-SHA256: {root_hex}\n"
        )
        statement_bytes = statement.encode("utf-8")

        priv, pub = get_signing_key(event.id)
        sig_bytes = merkle.sign_data(priv, statement_bytes)
        sig_b64 = base64.b64encode(sig_bytes).decode("ascii")
        pub_pem = merkle.export_public_key_pem(pub).decode("ascii")

        signed_root = SignedRoot.objects.create(
            id=f"sroot_{event.id}_{pub_seq}",
            event=event,
            publish_seq=pub_seq,
            root_hash=root_hex,
            leaf_count=len(leaves),
            signature_ed25519=sig_b64,
            public_key_pem=pub_pem,
            statement=statement,
            created_at=timezone.now(),
        )

        # 5. Generate judge protocols with inclusion proofs
        judge_ids = {r["judge_id"] for r in review_map}
        for jid in judge_ids:
            judge_person = Person.objects.filter(id=jid).first()
            if not judge_person:
                continue

            judge_reviews = [r for r in review_map if r["judge_id"] == jid]
            protocol_payload = []

            for jr in judge_reviews:
                proof = merkle.generate_inclusion_proof(jr["index"], leaves) if leaves else []
                protocol_payload.append({
                    "submission_id": jr["submission_id"],
                    "criterion_id": jr["criterion_id"],
                    "score": jr["score"],
                    "comment": jr["comment"],
                    "leaf_hash": jr["leaf_hash"],
                    "canonical_row": jr["canonical_row"],
                    "inclusion_proof": proof,
                })

            proto_stmt = f"JUDGE PROTOCOL\nEvent: {event.id}\nJudge: {jid}\nRoot: {root_hex}\nReviews: {len(judge_reviews)}\n"
            proto_sig = base64.b64encode(merkle.sign_data(priv, proto_stmt.encode("utf-8"))).decode("ascii")
            cert_no = f"CERT-JDG-{event.id}-{jid}"

            JudgeProtocol.objects.update_or_create(
                event=event,
                judge=judge_person,
                defaults={
                    "id": f"proto_{event.id}_{jid}_{pub_seq}",
                    "root": signed_root,
                    "certificate_number": cert_no,
                    "reviews_payload": protocol_payload,
                    "statement_hash": hashlib.sha256(proto_stmt.encode("utf-8")).hexdigest(),
                    "signature_ed25519": proto_sig,
                    "created_at": timezone.now(),
                },
            )

        return signed_root


def get_latest_signed_root(event: Event) -> SignedRoot | None:
    return SignedRoot.objects.filter(event=event).order_by("-publish_seq").first()
