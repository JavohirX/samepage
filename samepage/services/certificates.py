"""Certificates service: rule-based award derivation, SVG generation, and verification (S8)."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import (
    Event,
    JudgeProtocol,
    Person,
    ResultsSnapshot,
    Team,
    TeamCertificate,
    TeamMember,
)
from samepage.domain import certificates, merkle
from samepage.services import audit
from samepage.services.signing import get_signing_key


def issue_certificates(
    event: Event,
    base_url: str = "http://localhost:8080",
    track_prizes: dict[str, str] | None = None,
    overall_prizes: list[str] | None = None,
    custom_overrides: dict[str, str] | None = None,
) -> list[TeamCertificate]:
    """Issue cryptographically signed SVG certificates for all teams in event."""
    snapshot = ResultsSnapshot.objects.filter(event=event).order_by("-seq").first()
    if not snapshot:
        raise NotFound("No published results available to generate certificates.")

    payload = snapshot.payload or {}
    ranking = payload.get("ranking") or []
    # If ranking is empty, gather submissions
    ranked_projects = []
    for r in ranking:
        ranked_projects.append({
            "id": r.get("submission_id") or r.get("id"),
            "track": r.get("track", ""),
        })

    awards = certificates.derive_awards(
        ranked_projects,
        track_prizes=track_prizes,
        overall_prizes=overall_prizes,
        custom_overrides=custom_overrides,
    )

    priv, pub = get_signing_key(event.id)
    pub_pem = merkle.export_public_key_pem(pub).decode("ascii")

    issued_certs: list[TeamCertificate] = []

    teams = list(Team.objects.filter(event=event).prefetch_related("members__person", "submissions"))
    with transaction.atomic():
        for t in teams:
            submission = t.submissions.filter(state="submitted").first() or t.submissions.first()
            proj_title = submission.title if submission else "Participant"
            proj_id = submission.id if submission else ""

            member_names = [m.person.name or m.person.email for m in t.members.all()]
            award_info = awards.get(proj_id, {"award": "Certificate of Participation", "is_winner": False})

            cert_no = f"CERT-TM-{event.id}-{t.id}"
            verification_url = f"{base_url.rstrip('/')}/certificates/{cert_no}"
            issued_date = timezone.now().strftime("%B %d, %Y")

            # Sign metadata payload
            payload_data = f"{cert_no}|{event.id}|{t.id}|{award_info['award']}|{issued_date}".encode("utf-8")
            payload_sha = hashlib.sha256(payload_data).hexdigest()
            sig_bytes = merkle.sign_data(priv, payload_data)
            sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

            svg_text = certificates.generate_certificate_svg(
                certificate_number=cert_no,
                event_name=event.name,
                team_name=t.name,
                project_title=proj_title,
                members=member_names,
                award_title=award_info["award"],
                issued_date=issued_date,
                verification_url=verification_url,
                signature_base64=sig_b64,
                payload_sha256=payload_sha,
            )

            cert, _ = TeamCertificate.objects.update_or_create(
                event=event,
                team=t,
                defaults={
                    "id": f"cert_{event.id}_{t.id}",
                    "certificate_number": cert_no,
                    "award_title": award_info["award"],
                    "is_winner": award_info["is_winner"],
                    "payload_sha256": payload_sha,
                    "signature_ed25519": sig_b64,
                    "public_key_pem": pub_pem,
                    "svg_content": svg_text,
                    "issued_at": timezone.now(),
                },
            )
            issued_certs.append(cert)

    return issued_certs


def get_certificate_by_number(cert_no: str) -> dict[str, Any]:
    """Look up certificate (team or judge protocol) by its unique number."""
    team_cert = TeamCertificate.objects.filter(certificate_number=cert_no).select_related("event", "team").first()
    if team_cert:
        return {
            "type": "team",
            "certificate_number": team_cert.certificate_number,
            "event_id": team_cert.event_id,
            "event_name": team_cert.event.name,
            "team_id": team_cert.team_id,
            "team_name": team_cert.team.name,
            "award": team_cert.award_title,
            "is_winner": team_cert.is_winner,
            "payload_sha256": team_cert.payload_sha256,
            "signature_ed25519": team_cert.signature_ed25519,
            "public_key_pem": team_cert.public_key_pem,
            "issued_at": team_cert.issued_at.isoformat(),
            "svg_download": f"/e/{team_cert.event_id}/teams/{team_cert.team_id}/certificate.svg",
        }

    judge_proto = JudgeProtocol.objects.filter(certificate_number=cert_no).select_related("event", "judge", "root").first()
    if judge_proto:
        return {
            "type": "judge",
            "certificate_number": judge_proto.certificate_number,
            "event_id": judge_proto.event_id,
            "event_name": judge_proto.event.name,
            "judge_id": judge_proto.judge_id,
            "statement_hash": judge_proto.statement_hash,
            "signature_ed25519": judge_proto.signature_ed25519,
            "root_hash": judge_proto.root.root_hash,
            "issued_at": judge_proto.created_at.isoformat(),
        }

    raise NotFound("Certificate not found.")
