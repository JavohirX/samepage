"""Dry Harbour is a decision. The default is keep-latest, and it stays provisional until a person confirms it."""

from __future__ import annotations

from django.db import transaction
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import DuplicateGroup, Submission
from samepage.domain.transitions import transition
from samepage.engine.snapshot import build_snapshot, rank_project
from samepage.services import audit, results
from samepage.services.ledger import review_rows, weights_for


def _norm_repo(url: str) -> str:
    return (url or "").strip().rstrip("/").casefold()


def detect(event_id: str) -> list[list[Submission]]:
    rows = list(Submission.objects.filter(event_id=event_id).order_by("position", "id"))
    used = set()
    found = []
    for index, left in enumerate(rows):
        if left.id in used:
            continue
        members = [left]
        for right in rows[index + 1 :]:
            if right.id in used or left.team_id != right.team_id:
                continue
            same_repo = bool(left.repo_url) and _norm_repo(left.repo_url) == _norm_repo(right.repo_url)
            same_title = bool(left.title) and left.title.casefold() == right.title.casefold()
            if same_repo or same_title:
                members.append(right)
        if len(members) > 1:
            for member in members:
                used.add(member.id)
            found.append(members)
    return found


def preview_ranks(event_id: str, members: list[Submission]) -> dict:
    """Rank of the kept project under each resolution, without writing."""
    weights = weights_for(event_id)
    rows = review_rows(event_id)
    member_ids = {row.id for row in members}
    latest = sorted(members, key=lambda row: (row.submitted_at.isoformat() if row.submitted_at else "", row.id))[-1]
    earlier = [row.id for row in members if row.id != latest.id]

    def fit(mode: str):
        reviews = []
        for row in rows:
            if not row["criteria"]:
                continue
            project = row["project_id"]
            if project in earlier:
                if mode == "merge":
                    reviews.append(
                        {"project_id": latest.id, "judge_id": row["judge_id"], "criteria": row["criteria"]}
                    )
                continue
            target = row["counts_as"] or (project if project == latest.id else None)
            if target is None:
                continue
            reviews.append({"project_id": target, "judge_id": row["judge_id"], "criteria": row["criteria"]})
        meta = {
            row.id: {
                "title": row.title,
                "track": row.track_id,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else "",
            }
            for row in Submission.objects.filter(event_id=event_id).exclude(id__in=earlier)
        }
        snapshot = build_snapshot(reviews, meta, weights, with_lojo=False, with_draws=False)
        return rank_project(snapshot, latest.id)

    return {"keep_latest": fit("keep_latest"), "merge": fit("merge"), "kept": latest.id}


@transaction.atomic
def ensure_provisional(event_id: str) -> list[DuplicateGroup]:
    created = []
    for index, members in enumerate(detect(event_id), start=1):
        group_id = f"dup_{index:02d}"
        if DuplicateGroup.objects.filter(id=group_id).exists():
            continue
        ordered = sorted(members, key=lambda row: (row.submitted_at.isoformat() if row.submitted_at else "", row.id))
        group = DuplicateGroup.objects.create(
            id=group_id,
            event_id=event_id,
            rule="same team and (same repo or same title)",
            members=[row.id for row in ordered],
            resolution="keep_latest",
            status="provisional",
            resolved_by="",
        )
        apply(group, actor="importer", reason="default rule keep_latest; awaiting organizer confirmation")
        created.append(group)
    return created


def apply(group: DuplicateGroup, *, actor: str, reason: str) -> None:
    members = list(Submission.objects.filter(id__in=group.members))
    ordered = sorted(members, key=lambda row: (row.submitted_at or row.id, row.id))
    latest = ordered[-1]
    for row in ordered[:-1]:
        row.duplicate_group = group
        row.merged_into = latest if group.resolution == "merge" else None
        row.state = "withdrawn"
        if group.resolution == "merge":
            row.withdrawn_reason = f"merged_into:{latest.id}"
        else:
            row.withdrawn_reason = f"duplicate_of:{latest.id}"
        row.save()
    latest.duplicate_group = group
    latest.merged_into = None
    if latest.state == "withdrawn" and latest.withdrawn_reason.startswith(("duplicate_of:", "merged_into:")):
        latest.state = "submitted"
        latest.withdrawn_reason = ""
        latest.save()
    else:
        latest.save(update_fields=["duplicate_group"])
    seq = audit.append(
        group.event_id,
        actor,
        "duplicate.apply",
        group.id,
        None,
        {"resolution": group.resolution, "status": group.status, "reason": reason, "kept": latest.id},
    )
    group.audit_seq = seq
    group.save(update_fields=["audit_seq"])


@transaction.atomic
def confirm(event_id: str, group_id: str, actor_id: str, resolution: str | None = None) -> DuplicateGroup:
    group = DuplicateGroup.objects.select_for_update().filter(event_id=event_id, id=group_id).first()
    if group is None:
        raise NotFound("Unknown decision.")
    transition("duplicate", group.status, "confirmed")
    if resolution:
        if resolution not in {"keep_latest", "merge"}:
            from samepage.core.errors import Unprocessable

            raise Unprocessable({"resolution": "choose keep_latest or merge"})
        group.resolution = resolution
    group.status = "confirmed"
    group.resolved_by = actor_id
    group.save()
    apply(group, actor=actor_id, reason=f"confirmed {group.resolution}")
    results.rebuild(event_id, actor=actor_id, cause=group.audit_seq)
    return group


def detail_payload(event_id: str, group_id: str) -> dict:
    group = DuplicateGroup.objects.filter(event_id=event_id, id=group_id).first()
    if group is None:
        raise NotFound("Unknown decision.")
    members = list(Submission.objects.filter(id__in=group.members).order_by("submitted_at"))
    # Previews are part of the page. They re-fit without the interval draws.
    try:
        ranks = preview_ranks(event_id, members)
    except Exception:
        ranks = {"keep_latest": None, "merge": None, "kept": members[-1].id if members else ""}
    items = [
        {
            "id": row.id,
            "title": row.title,
            "team_id": row.team_id,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else "",
            "state": row.state,
            "repo_url": row.repo_url,
        }
        for row in members
    ]
    return {
        "title": f"Duplicate {group.id}",
        "event": event_id,
        "resource": "duplicate",
        "id": group.id,
        "status": group.status,
        "resolution": group.resolution,
        "rule": group.rule,
        "kept": ranks.get("kept"),
        "preview_keep_latest_rank": ranks.get("keep_latest"),
        "preview_merge_rank": ranks.get("merge"),
        "columns": ["id", "title", "team_id", "submitted_at", "state", "repo_url"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/duplicates/{group.id}.csv",
        "download_json": f"/e/{event_id}/duplicates/{group.id}.json",
        "html_omitted": {},
    }


def list_payload(event_id: str) -> dict:
    groups = DuplicateGroup.objects.filter(event_id=event_id).order_by("id")
    items = [
        {
            "id": group.id,
            "status": group.status,
            "resolution": group.resolution,
            "members": " ".join(group.members),
            "rule": group.rule,
        }
        for group in groups
    ]
    return {
        "title": "Duplicates",
        "event": event_id,
        "resource": "duplicates",
        "columns": ["id", "status", "resolution", "members", "rule"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/duplicates.csv",
        "download_json": f"/e/{event_id}/duplicates.json",
        "html_omitted": {},
    }
