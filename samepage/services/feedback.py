"""Feedback service: distribution-first feedback packs and release management (S9)."""

from __future__ import annotations

import statistics
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import (
    Criterion,
    Event,
    FeedbackRelease,
    Person,
    ResultsSnapshot,
    ScoreCurrent,
    Submission,
    Team,
)
from samepage.domain import feedback
from samepage.services import audit


def is_feedback_released(event: Event) -> bool:
    """Check if feedback has been released by an organizer."""
    return FeedbackRelease.objects.filter(event=event).exists()


def release_feedback(event: Event, actor: Person) -> FeedbackRelease:
    """Release feedback packs to teams. Audited action."""
    if event.state != "published" and event.state != "archived":
        raise PermissionDenied("Feedback can only be released after results are published.")

    with transaction.atomic():
        rel = FeedbackRelease.objects.filter(event=event).first()
        if rel:
            return rel

        seq = audit.append(
            event.id,
            actor.email if actor else "admin",
            "feedback.release",
            f"event/{event.id}/feedback",
            {"released": False},
            {"released": True, "by": actor.email if actor else "admin"},
        )

        rel = FeedbackRelease.objects.create(
            event=event,
            released_by=actor,
            released_at=timezone.now(),
            audit_seq=seq,
        )
        return rel


def get_team_feedback(event: Event, team: Team, *, allow_unreleased: bool = False) -> dict[str, Any]:
    """Compile distribution-first feedback pack for a team."""
    if not allow_unreleased and not is_feedback_released(event):
        raise PermissionDenied("Feedback packs have not been released yet.")

    submission = team.submissions.filter(state="submitted").first() or team.submissions.first()
    if not submission:
        raise NotFound("No submission found for this team.")

    # 1. Gather all project finalized scores to calculate distribution
    snapshot = ResultsSnapshot.objects.filter(event=event).order_by("-seq").first()
    all_scores: list[float] = []
    team_overall: float = 0.0

    if snapshot and snapshot.payload and "ranking" in snapshot.payload:
        for r in snapshot.payload["ranking"]:
            sc = float(r.get("score", 0.0))
            all_scores.append(sc)
            pid = r.get("submission_id") or r.get("id")
            if pid == submission.id:
                team_overall = sc
    else:
        # Fallback: calculate from raw ReviewScores
        pass

    if not all_scores and team_overall > 0:
        all_scores = [team_overall]

    # 2. Gather per-criterion means and non-empty anonymous comments for this submission
    scores = list(
        ScoreCurrent.objects.filter(
            submission=submission,
            state="final",
        )
    )

    criteria_scores: dict[str, list[float]] = {}
    comments: list[str] = []

    for s in scores:
        criteria_scores.setdefault(s.criterion, []).append(float(s.value))
        cmt = s.comment.strip()
        if cmt and cmt not in comments:
            comments.append(cmt)

    criteria_means = {
        crit: round(statistics.mean(vals), 2)
        for crit, vals in criteria_scores.items()
        if vals
    }

    pack = feedback.build_feedback_pack(
        project_id=submission.id,
        project_title=submission.title,
        overall_score=team_overall,
        all_project_scores=all_scores,
        criteria_means=criteria_means,
        anonymous_comments=comments,
    )
    pack["team_id"] = team.id
    pack["team_name"] = team.name
    return pack


def get_all_teams_feedback_summary(event: Event) -> list[dict[str, Any]]:
    """Gather feedback rows for all teams (for organizer mail-merge CSV)."""
    teams = list(Team.objects.filter(event=event).prefetch_related("submissions"))
    items = []
    for t in teams:
        sub = t.submissions.filter(state="submitted").first() or t.submissions.first()
        if not sub:
            continue
        try:
            # Bypass released check for staff export if needed, or check released
            fb = get_team_feedback(event, t)
            crit_summary = "; ".join(f"{k}: {v}" for k, v in fb["criteria_means"].items())
            cmt_summary = " // ".join(fb["comments"])
            items.append({
                "team_id": t.id,
                "team_name": t.name,
                "project_id": sub.id,
                "project_title": sub.title,
                "overall_score": fb["overall_score"],
                "percentile": fb["percentile"],
                "criteria_means": crit_summary,
                "comments": cmt_summary,
            })
        except PermissionDenied:
            continue
    return items
