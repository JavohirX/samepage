"""Comments service: creation, pre-moderation (approve/reject), and public views."""

from __future__ import annotations

import secrets
from typing import Any

from django.db import transaction
from django.utils.html import escape
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import Event, Person, ProjectComment, Submission
from samepage.core.errors import Unprocessable
from samepage.services import audit
from samepage.services.clock import db_now


def post_comment(
    submission: Submission,
    author: Person,
    text: str,
) -> ProjectComment:
    """Post a comment on a submitted project.

    New comments start in 'pending' status (S6: pre-moderation).
    """
    clean_text = text.strip()
    if not clean_text:
        raise Unprocessable("Comment text cannot be empty.")
    if len(clean_text) > 2000:
        raise Unprocessable("Comment text cannot exceed 2000 characters.")

    event = submission.event
    now = db_now()

    with transaction.atomic():
        comment = ProjectComment.objects.create(
            id=f"cmt_{secrets.token_hex(6)}",
            submission=submission,
            event=event,
            author=author,
            text=clean_text,
            state="pending",
            created_at=now,
        )
        seq = audit.append(
            event.id,
            author.email,
            "comment.create",
            f"event/{event.id}/projects/{submission.id}/comments/{comment.id}",
            None,
            {"author_id": author.id, "state": "pending"},
        )
        comment.audit_seq = seq
        comment.save(update_fields=["audit_seq"])
        return comment


def approve_comment(comment_id: str, reviewer: Person) -> ProjectComment:
    with transaction.atomic():
        comment = ProjectComment.objects.select_for_update().filter(id=comment_id).first()
        if not comment:
            raise NotFound("Comment not found.")
        before = {"state": comment.state}
        comment.state = "approved"
        comment.reviewed_by = reviewer
        comment.reviewed_at = db_now()
        comment.save()

        seq = audit.append(
            comment.event_id,
            reviewer.email,
            "comment.approve",
            f"event/{comment.event_id}/projects/{comment.submission_id}/comments/{comment.id}",
            before,
            {"state": "approved", "reviewer": reviewer.email},
        )
        comment.audit_seq = seq
        comment.save(update_fields=["audit_seq"])
        return comment


def reject_comment(comment_id: str, reviewer: Person, reason: str = "") -> ProjectComment:
    with transaction.atomic():
        comment = ProjectComment.objects.select_for_update().filter(id=comment_id).first()
        if not comment:
            raise NotFound("Comment not found.")
        before = {"state": comment.state}
        comment.state = "rejected"
        comment.reviewed_by = reviewer
        comment.reviewed_at = db_now()
        comment.rejection_reason = reason.strip()
        comment.save()

        seq = audit.append(
            comment.event_id,
            reviewer.email,
            "comment.reject",
            f"event/{comment.event_id}/projects/{comment.submission_id}/comments/{comment.id}",
            before,
            {"state": "rejected", "reviewer": reviewer.email, "reason": reason.strip()},
        )
        comment.audit_seq = seq
        comment.save(update_fields=["audit_seq"])
        return comment


def list_public_comments(submission: Submission) -> list[dict[str, Any]]:
    """Return only approved comments for public display. Text is HTML-escaped."""
    comments = (
        ProjectComment.objects.filter(submission=submission, state="approved")
        .select_related("author")
        .order_by("created_at")
    )
    return [
        {
            "id": c.id,
            "author_name": escape(c.author.name or c.author.email.split("@")[0]),
            "text": escape(c.text),
            "created_at": c.created_at.isoformat(),
        }
        for c in comments
    ]


def list_moderation_queue(event: Event) -> list[dict[str, Any]]:
    """Return all comments for organizers (moderation queue)."""
    comments = (
        ProjectComment.objects.filter(event=event)
        .select_related("author", "submission", "reviewed_by")
        .order_by("-created_at")
    )
    return [
        {
            "id": c.id,
            "project_id": c.submission_id,
            "project_title": c.submission.title,
            "author_email": c.author.email,
            "author_name": c.author.name,
            "text": c.text,
            "state": c.state,
            "created_at": c.created_at.isoformat(),
            "reviewed_by": c.reviewed_by.email if c.reviewed_by else None,
            "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
            "rejection_reason": c.rejection_reason,
        }
        for c in comments
    ]
