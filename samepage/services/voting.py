"""Voting service: configuration, ballots, magic links, audit, and tallies."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from samepage.apps.portal.models import (
    Ballot,
    BallotLine,
    Event,
    MailOutbox,
    Person,
    Submission,
    TeamMember,
    VotingConfig,
    VotingTally,
)
from samepage.core.errors import Unprocessable
from samepage.domain.voting import balanced_rotation, compute_tallies
from samepage.services import audit
from samepage.services.clock import db_now


def get_or_create_config(event: Event) -> VotingConfig:
    config, _ = VotingConfig.objects.get_or_create(
        event=event,
        defaults={
            "id": f"vc_{secrets.token_hex(6)}",
            "credit_budget": 25,
            "allow_accounts": True,
            "allow_open": False,
            "allow_email": False,
            "state": "draft",
        },
    )
    return config


def update_config(event: Event, actor: str, **kwargs) -> VotingConfig:
    with transaction.atomic():
        config = get_or_create_config(event)
        before = {
            "credit_budget": config.credit_budget,
            "allow_accounts": config.allow_accounts,
            "allow_open": config.allow_open,
            "allow_email": config.allow_email,
            "state": config.state,
            "opens_at": config.opens_at.isoformat() if config.opens_at else None,
            "closes_at": config.closes_at.isoformat() if config.closes_at else None,
        }

        if "credit_budget" in kwargs:
            b = int(kwargs["credit_budget"])
            if b <= 0:
                raise Unprocessable("Credit budget must be greater than 0.")
            config.credit_budget = b

        if "allow_accounts" in kwargs:
            config.allow_accounts = bool(kwargs["allow_accounts"])

        if "allow_open" in kwargs:
            config.allow_open = bool(kwargs["allow_open"])
            if config.allow_open and not config.open_token:
                config.open_token = secrets.token_urlsafe(24)

        if "allow_email" in kwargs:
            config.allow_email = bool(kwargs["allow_email"])

        if "opens_at" in kwargs:
            opens_at = kwargs["opens_at"]
            if opens_at is not None and event.submissions_close and opens_at < event.submissions_close:
                raise Unprocessable("Voting window cannot open before submissions close.")
            config.opens_at = opens_at

        if "closes_at" in kwargs:
            closes_at = kwargs["closes_at"]
            if closes_at is not None and config.opens_at and closes_at <= config.opens_at:
                raise Unprocessable("Voting window must close after it opens.")
            config.closes_at = closes_at

        if "state" in kwargs:
            st = kwargs["state"]
            if st in ("draft", "open", "closed"):
                config.state = st

        config.save()
        after = {
            "credit_budget": config.credit_budget,
            "allow_accounts": config.allow_accounts,
            "allow_open": config.allow_open,
            "allow_email": config.allow_email,
            "state": config.state,
            "opens_at": config.opens_at.isoformat() if config.opens_at else None,
            "closes_at": config.closes_at.isoformat() if config.closes_at else None,
        }
        audit.append(event.id, actor, "voting.config", f"event/{event.id}/voting", before, after)
        return config


def get_voter_rotation_index(event: Event, voter_key: str) -> int:
    """Stable voter sequence index for balanced rotation (S4)."""
    # Deterministic integer derived from voter key + event
    h = hashlib.sha256(f"{event.id}:{voter_key}".encode("utf-8")).hexdigest()
    return int(h[:6], 16)


def get_projects_for_voter(event: Event, voter_key: str) -> list[Submission]:
    """Get active submitted projects for event in balanced rotated order."""
    submissions = list(
        Submission.objects.filter(event=event, state="submitted")
        .exclude(merged_into__isnull=False)
        .order_by("id")
    )
    if not submissions:
        return []
    idx = get_voter_rotation_index(event, voter_key)
    return balanced_rotation(submissions, idx)


def check_eligibility(
    event: Event, person: Person | None, voter_type: str
) -> tuple[bool, bool, str, str]:
    """Returns (is_eligible, is_excluded, exclusion_reason, channel).

    channel: 'participants' | 'public'
    is_excluded: True if account made after event.submissions_close (S3).
    """
    config = get_or_create_config(event)
    now = db_now()

    # Check window
    if config.state == "closed" or config.state == "counted":
        raise Unprocessable("Voting is closed.")
    if config.state != "open":
        raise Unprocessable("Voting is not open.")
    if config.opens_at and now < config.opens_at:
        raise Unprocessable("Voting has not opened yet.")
    if config.closes_at and now > config.closes_at:
        raise Unprocessable("Voting window has closed.")

    channel = "public"
    is_excluded = False
    reason = ""

    if voter_type == "account":
        if not config.allow_accounts:
            raise Unprocessable("Account voting is not enabled for this event.")
        if person is None:
            raise Unprocessable("Authentication required for account voting.")

        # Check cutoff at submissions_close (S3)
        if event.submissions_close and person.created_at > event.submissions_close:
            is_excluded = True
            reason = "account_created_after_submission_deadline"

        # Check if participant on a team
        if TeamMember.objects.filter(event=event, person=person).exists():
            channel = "participants"
        else:
            channel = "public"

    elif voter_type == "open":
        if not config.allow_open:
            raise Unprocessable("Open link voting is not enabled for this event.")
        channel = "public"

    elif voter_type == "email":
        if not config.allow_email:
            raise Unprocessable("Email voting is not enabled for this event.")
        channel = "public"

    return True, is_excluded, reason, channel


def cast_ballot(
    event: Event,
    voter_type: str,
    votes: dict[str, int],
    *,
    person: Person | None = None,
    session_key: str = "",
    voter_email: str = "",
    client_ip: str | None = None,
) -> Ballot:
    with transaction.atomic():
        config = get_or_create_config(event)
        _, is_excluded, exclusion_reason, channel = check_eligibility(event, person, voter_type)

        # Validate budget
        total_credits = sum(int(c) for c in votes.values() if int(c) > 0)
        if total_credits > config.credit_budget:
            raise Unprocessable(
                f"Ballot exceeds credit budget of {config.credit_budget} (spent {total_credits})."
            )

        # Validate projects exist and belong to event
        active_pids = set(
            Submission.objects.filter(event=event, state="submitted")
            .exclude(merged_into__isnull=False)
            .values_list("id", flat=True)
        )
        for pid in votes.keys():
            if pid not in active_pids:
                raise Unprocessable(f"Unknown project {pid}.")

        # Find or create ballot
        ballot = None
        if voter_type == "account" and person:
            ballot = Ballot.objects.filter(event=event, person=person).first()
        elif voter_type == "open" and session_key:
            ballot = Ballot.objects.filter(event=event, session_key=session_key).first()
        elif voter_type == "email" and voter_email:
            ballot = Ballot.objects.filter(event=event, voter_email=voter_email).first()

        voter_ident = str(person.id if person else (session_key or voter_email))
        seq_num = get_voter_rotation_index(event, voter_ident)

        if ballot is None:
            ballot = Ballot.objects.create(
                id=f"bal_{secrets.token_hex(6)}",
                event=event,
                voter_type=voter_type,
                person=person,
                session_key=session_key,
                voter_email=voter_email,
                sequence_number=seq_num,
                channel=channel,
                excluded=is_excluded,
                exclusion_reason=exclusion_reason,
                credits_spent=total_credits,
                client_ip=client_ip,
                created_at=db_now(),
            )
        else:
            ballot.credits_spent = total_credits
            ballot.channel = channel
            ballot.excluded = is_excluded
            ballot.exclusion_reason = exclusion_reason
            ballot.client_ip = client_ip
            ballot.save()
            ballot.lines.all().delete()

        # Create ballot lines
        for pid, cr in votes.items():
            cr_int = int(cr)
            if cr_int > 0:
                BallotLine.objects.create(
                    ballot=ballot,
                    submission_id=pid,
                    credits=cr_int,
                )

        actor_str = person.email if person else (voter_email or f"session:{session_key[:8]}")
        audit.append(
            event.id,
            actor_str,
            "voting.ballot",
            f"event/{event.id}/ballots/{ballot.id}",
            None,
            {
                "ballot_id": ballot.id,
                "voter_type": voter_type,
                "channel": channel,
                "credits_spent": total_credits,
                "excluded": is_excluded,
            },
        )
        return ballot


def request_magic_link(event: Event, email: str, base_url: str) -> MailOutbox:
    config = get_or_create_config(event)
    if not config.allow_email:
        raise Unprocessable("Email voting is not enabled for this event.")

    token = secrets.token_urlsafe(32)
    token_sha = hashlib.sha256(token.encode("utf-8")).hexdigest()
    magic_url = f"{base_url.rstrip('/')}/vote/magic/{token}"
    now = db_now()

    outbox = MailOutbox.objects.create(
        id=f"mob_{secrets.token_hex(6)}",
        event=event,
        recipient_email=email.strip().lower(),
        subject=f"Vote in {event.name}",
        token_sha256=token_sha,
        magic_url=magic_url,
        expires_at=now + timedelta(minutes=15),
        created_at=now,
    )
    return outbox


def redeem_magic_link(token: str) -> tuple[Event, str]:
    token_sha = hashlib.sha256(token.encode("utf-8")).hexdigest()
    outbox = MailOutbox.objects.filter(token_sha256=token_sha).first()
    if not outbox:
        raise Unprocessable("Invalid or expired magic link.")
    if outbox.used_at is not None:
        raise Unprocessable("Magic link has already been used.")
    if outbox.expires_at < db_now():
        raise Unprocessable("Magic link has expired.")

    outbox.used_at = db_now()
    outbox.save(update_fields=["used_at"])
    return outbox.event, outbox.recipient_email


def close_and_count(event: Event, actor: str) -> VotingTally:
    with transaction.atomic():
        config = get_or_create_config(event)
        if hasattr(event, "voting_tally"):
            return event.voting_tally

        config.state = "counted"
        config.closed_at = db_now()
        config.counted_at = db_now()
        config.save()

        # Collect active projects
        project_ids = list(
            Submission.objects.filter(event=event, state="submitted")
            .exclude(merged_into__isnull=False)
            .order_by("id")
            .values_list("id", flat=True)
        )

        # Collect ballots and lines
        ballots_raw = []
        for b in Ballot.objects.filter(event=event).prefetch_related("lines"):
            votes_map = {line.submission_id: line.credits for line in b.lines.all()}
            ballots_raw.append({
                "id": b.id,
                "channel": b.channel,
                "excluded": b.excluded,
                "votes": votes_map,
            })

        tally_payload = compute_tallies(ballots_raw, project_ids)

        seq = audit.append(
            event.id,
            actor,
            "voting.close",
            f"event/{event.id}/voting",
            None,
            {
                "total_ballots": tally_payload["ballot_counts"]["total"],
                "counted_ballots": tally_payload["ballot_counts"]["counted"],
                "excluded_ballots": tally_payload["ballot_counts"]["excluded"],
            },
        )

        tally = VotingTally.objects.create(
            id=f"vt_{secrets.token_hex(6)}",
            event=event,
            created_at=db_now(),
            created_by=actor,
            audit_seq=seq,
            payload=tally_payload,
        )
        return tally


def get_tally(event: Event, is_staff: bool) -> dict[str, Any]:
    """Get voting tally.

    Before close:
      - Non-staff: 403 Forbidden.
      - Staff: Only sees ballot count, NOT project scores/rankings (S5).
    After close:
      - Everyone: Frozen tally payload with participants, public, and combined tables.
    """
    if hasattr(event, "voting_tally"):
        return event.voting_tally.payload

    if not is_staff:
        raise PermissionDenied("Voting results are hidden until voting closes.")

    # Staff before close only gets ballot counts
    total_ballots = Ballot.objects.filter(event=event).count()
    return {
        "status": "in_progress",
        "ballot_counts": {
            "total": total_ballots,
        },
        "message": "Results are hidden until an organizer closes and counts the vote.",
    }
