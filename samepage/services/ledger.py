"""The rows behind every number. HTML, JSON and CSV are projections of these lists."""

from __future__ import annotations

import csv
import io
from collections import defaultdict

from django.db.models import Max, Q
from django.utils import timezone

from samepage.apps.portal.models import (
    Assignment,
    Batch,
    Criterion,
    DuplicateGroup,
    ScoreCurrent,
    Submission,
    Track,
)
from samepage.domain.weighted import fraction_text, weighted_total

SCORE_HEAD = ["id", "judge_id", "project_id", "track"]
SCORE_TAIL = [
    "weighted_total",
    "comment",
    "state",
    "counted",
    "excluded_reason",
    "merged_into",
    "audit_seq",
]
# The fixture's rubric. An event with other criteria gets c_<key> columns for its own keys.
SCORE_COLUMNS = SCORE_HEAD + ["c_functionality", "c_quality", "c_innovation"] + SCORE_TAIL

# Withdrawn by a duplicate decision, under either resolution (duplicate_of: or merged_into:).
# A withdrawal by the team or an organizer is not one, even for a project in a duplicate group.
DUPLICATE_WITHDRAWAL = Q(state="withdrawn", duplicate_group__isnull=False) & (
    Q(withdrawn_reason__startswith="duplicate_of:") | Q(withdrawn_reason__startswith="merged_into:")
)


def weights_for(event_id: str) -> dict[str, str]:
    rows = Criterion.objects.filter(event_id=event_id, track__isnull=True).order_by("position", "key")
    found = {row.key: str(row.weight) for row in rows}
    if found:
        return found
    return {"functionality": "1", "quality": "1", "innovation": "1"}


def track_weights(event_id: str) -> dict[str, dict[str, str]]:
    """Per-track weights: the event's weights, with any track override on top."""
    base = weights_for(event_id)
    merged: dict[str, dict[str, str]] = {}
    for row in Criterion.objects.filter(event_id=event_id, track__isnull=False):
        if row.key in base:
            merged.setdefault(row.track_id, dict(base))[row.key] = str(row.weight)
    return merged


def criterion_keys(event_id: str) -> list[str]:
    return list(weights_for(event_id))


def score_columns(event_id: str) -> list[str]:
    return SCORE_HEAD + [f"c_{key}" for key in criterion_keys(event_id)] + SCORE_TAIL


def review_rows(event_id: str) -> list[dict]:
    """One dict per judge×project. `counted` is the string true/false used in the CSV."""
    current = (
        ScoreCurrent.objects.filter(submission__event_id=event_id)
        .select_related("submission", "submission__track", "submission__duplicate_group", "submission__merged_into")
    )
    grouped: dict[tuple[str, str], dict] = {}
    for row in current:
        slot = grouped.setdefault(
            (row.judge_id, row.submission_id),
            {"criteria": {}, "comments": [], "states": [], "audit": [], "submission": row.submission},
        )
        slot["criteria"][row.criterion] = int(row.value)
        if row.comment:
            slot["comments"].append(row.comment)
        slot["states"].append(row.state)
        slot["audit"].append(row.audit_seq)
    weights = weights_for(event_id)
    per_track = track_weights(event_id)
    keys = list(weights)
    items = []
    for (judge_id, submission_id), slot in grouped.items():
        submission = slot["submission"]
        counted, reason, counts_as = _count(submission)
        own_weights = per_track.get(submission.track_id, weights)
        try:
            total = weighted_total(slot["criteria"], own_weights)
            total_text = fraction_text(total)
        except ValueError:
            total = None
            total_text = ""
        comment = slot["comments"][0] if slot["comments"] else ""
        final = bool(slot["states"]) and all(item == "final" for item in slot["states"])
        state = "final" if final else ("draft" if "draft" in slot["states"] else slot["states"][0] if slot["states"] else "")
        if counted and not final:
            # Only a finalized review counts. A draft or a reopened (unlocked) score is in the ledger, not in the fit.
            counted, reason, counts_as = False, f"not_final:{state}", None
        elif counted and total is None:
            counted, reason, counts_as = False, "incomplete_rubric", None
        row = {
            "id": f"{judge_id}:{submission_id}",
            "judge_id": judge_id,
            "project_id": submission_id,
            "track": submission.track_id,
            "criteria": slot["criteria"],
            "weights": own_weights,
        }
        for key in keys:
            row[f"c_{key}"] = slot["criteria"].get(key, "")
        items.append(
            {
                **row,
                "weighted_total": total_text,
                "weighted_value": None if total is None else float(total),
                "comment": comment,
                "state": state,
                "counted": "true" if counted else "false",
                "excluded_reason": reason,
                "merged_into": submission.merged_into_id or "",
                "counts_as": counts_as,
                "audit_seq": max(slot["audit"]) if slot["audit"] else "",
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
                "title": submission.title,
            }
        )
    items.sort(key=lambda row: (row["judge_id"], row["project_id"]))
    return items


def _count(submission: Submission):
    if submission.state != "withdrawn":
        return True, "", submission.id
    if submission.merged_into_id:
        return True, "", submission.merged_into_id
    reason = ""
    if submission.duplicate_group_id and submission.withdrawn_reason.startswith("duplicate_of:"):
        reason = f"withdrawn_duplicate:{submission.duplicate_group_id}"
    elif submission.withdrawn_reason:
        reason = submission.withdrawn_reason
    return False, reason, None


def filter_reviews(rows: list[dict], query) -> list[dict]:
    counted = query.get("counted")
    judge = query.get("judge")
    project = query.get("project")
    kept = []
    for row in rows:
        if counted in {"true", "false"} and row["counted"] != counted:
            continue
        if judge and row["judge_id"] != judge:
            continue
        if project and row["project_id"] != project:
            continue
        kept.append(row)
    return kept


def score_payload(event_id: str, query) -> dict:
    rows = filter_reviews(review_rows(event_id), query)
    columns = score_columns(event_id)
    items = [{key: row.get(key, "") for key in columns} for row in rows]
    return {
        "title": "Scores",
        "event": event_id,
        "resource": "scores",
        "count": len(items),
        "columns": columns,
        "numeric_columns": [column for column in columns if column.startswith("c_")],
        "items": items,
        "html_omitted": {},
        "download_csv": f"/e/{event_id}/scores.csv",
        "download_json": f"/e/{event_id}/scores.json",
    }


def counted_for_engine(event_id: str) -> tuple[list[dict], dict]:
    reviews = []
    meta = {}
    for row in review_rows(event_id):
        if row["counts_as"] is None or row["weighted_value"] is None:
            continue
        if not row["criteria"]:
            continue
        reviews.append(
            {
                "project_id": row["counts_as"],
                "judge_id": row["judge_id"],
                "criteria": row["criteria"],
                "weights": row["weights"],
            }
        )
    for submission in Submission.objects.filter(event_id=event_id).exclude(state__in=("withdrawn", "draft")):
        meta[submission.id] = {
            "title": submission.title,
            "track": submission.track_id,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
        }
    return reviews, meta


def progress_payload(event_id: str) -> dict:
    rows = review_rows(event_id)
    def count(query):
        return len(filter_reviews(rows, query))

    counted = count({"counted": "true"})
    excluded = count({"counted": "false"})
    total = count({})
    per_project = defaultdict(int)
    for row in rows:
        if row["counted"] == "true":
            per_project[row["project_id"]] += 1
    active = list(
        Submission.objects.filter(event_id=event_id)
        .exclude(state__in=("withdrawn", "draft"))
        .values_list("id", flat=True)
    )
    full = sum(1 for project_id in active if per_project[project_id] >= 3)
    short = sum(1 for project_id in active if per_project[project_id] < 3)
    withdrawn = Submission.objects.filter(DUPLICATE_WITHDRAWAL, event_id=event_id).count()
    metrics = [
        {"key": "counted", "value": counted, "label": "counted", "href": f"/e/{event_id}/scores.csv?counted=true"},
        {"key": "excluded", "value": excluded, "label": "excluded", "href": f"/e/{event_id}/scores.csv?counted=false"},
        {"key": "total", "value": total, "label": "total", "href": f"/e/{event_id}/scores.csv"},
        {"key": "fully_reviewed", "value": full, "label": "fully reviewed", "href": f"/e/{event_id}/projects.csv?review=full"},
        {"key": "short", "value": short, "label": "short", "href": f"/e/{event_id}/projects.csv?review=short"},
        {"key": "withdrawn_duplicate", "value": withdrawn, "label": "withdrawn duplicate", "href": f"/e/{event_id}/projects.csv?state=withdrawn&duplicate=1"},
    ]
    # Each number is compared with the CSV its link downloads: the same payload builder the
    # CSV route calls, serialised by the CSV renderer, parsed back and counted.
    recounts = csv_recounts(event_id)
    for metric in metrics:
        metric["csv_rows"] = recounts[metric["key"]]
        metric["matches_csv"] = "true" if metric["value"] == recounts[metric["key"]] else "false"
    matched = sum(1 for metric in metrics if metric["value"] == recounts[metric["key"]])
    provisional = list(
        DuplicateGroup.objects.filter(event_id=event_id, status="provisional").values_list("id", flat=True)
    )
    return {
        "title": "Progress",
        "event": event_id,
        "resource": "progress",
        "sentence": {
            "counted": counted,
            "excluded": excluded,
            "total": total,
            "fully_reviewed": full,
            "active": len(active),
            "short": short,
            "withdrawn_duplicate": withdrawn,
        },
        "metrics": metrics,
        "items": metrics,
        "columns": ["key", "value", "label", "href", "csv_rows", "matches_csv"],
        "recount": {"matched": matched, "total": len(metrics)},
        "provisional": list(provisional),
        "batches": batch_rows(event_id),
        "judges": _judge_progress(event_id),
        "download_csv": f"/e/{event_id}/progress.csv",
        "download_json": f"/e/{event_id}/progress.json",
        "html_omitted": {},
    }


def _judge_progress(event_id: str) -> list[dict]:
    from samepage.services.judging import judge_progress

    return judge_progress(event_id)


def csv_data_rows(payload: dict) -> int:
    """Data rows in the CSV that `payload` renders to, counted by parsing the bytes."""
    from samepage.core.renderers import to_csv

    reader = csv.reader(io.StringIO(to_csv(payload)))
    next(reader, None)
    return sum(1 for _row in reader)


def csv_recounts(event_id: str) -> dict[str, int]:
    """Row counts of the six CSV links on the progress page, as an organizer downloads them."""
    return {
        "counted": csv_data_rows(score_payload(event_id, {"counted": "true"})),
        "excluded": csv_data_rows(score_payload(event_id, {"counted": "false"})),
        "total": csv_data_rows(score_payload(event_id, {})),
        "fully_reviewed": csv_data_rows(
            project_rows(event_id, include_withdrawn=False, query={"review": "full"}, paginate=False)
        ),
        "short": csv_data_rows(
            project_rows(event_id, include_withdrawn=False, query={"review": "short"}, paginate=False)
        ),
        "withdrawn_duplicate": csv_data_rows(
            project_rows(
                event_id, include_withdrawn=True, query={"state": "withdrawn", "duplicate": "1"}, paginate=False
            )
        ),
    }


def batch_rows(event_id: str) -> list[dict]:
    now = timezone.now()
    batches = Batch.objects.filter(event_id=event_id).select_related("judge", "run")
    items = []
    for batch in batches:
        assigned = Assignment.objects.filter(batch=batch)
        total = assigned.count()
        done = assigned.filter(finalized_at__isnull=False).count()
        last = ScoreCurrent.objects.filter(
            judge_id=batch.judge_id, submission__assignments__batch=batch
        ).aggregate(last=Max("audit_seq"))
        # Stalled: in progress and no score activity. Imported finals count as activity,
        # so a finished import batch is not stalled. We flag in_progress only.
        stalled = batch.state == "in_progress" and done < total
        items.append(
            {
                "id": batch.id,
                "judge_id": batch.judge_id,
                "judge": batch.judge.name or batch.judge.email,
                "state": batch.state,
                "kind": batch.run.kind,
                "completed": done,
                "assigned": total,
                "stalled": "true" if stalled else "false",
            }
        )
    items.sort(key=lambda row: row["id"])
    return items


def _many(query, key: str) -> list[str]:
    """?track=a&track=b, or ?track=a,b. A QueryDict or a plain dict."""
    if hasattr(query, "getlist"):
        raw = query.getlist(key)
    else:
        value = query.get(key)
        raw = value if isinstance(value, list) else ([value] if value else [])
    values = []
    for item in raw:
        values.extend(part.strip() for part in str(item).split(",") if part.strip())
    return list(dict.fromkeys(values))


def project_rows(
    event_id: str, *, include_withdrawn: bool, query, paginate: bool = True, include_drafts: bool = False
) -> dict:
    rows = review_rows(event_id)
    per = defaultdict(int)
    for row in rows:
        if row["counted"] == "true":
            per[row["project_id"]] += 1
    qs = Submission.objects.filter(event_id=event_id).select_related("track", "team")
    if not include_withdrawn:
        qs = qs.exclude(state="withdrawn")
    if not include_drafts:
        # A draft is the team's work in progress. The public gallery lists submitted projects only.
        qs = qs.exclude(state="draft")
    state = query.get("state")
    if state == "withdrawn":
        qs = Submission.objects.filter(event_id=event_id, state="withdrawn").select_related("track", "team")
    elif state and state != "all":
        qs = qs.filter(state=state)
    duplicate = query.get("duplicate") in {"1", "true"}
    if duplicate:
        # Only projects a duplicate decision withdrew: the rows behind "withdrawn duplicate".
        qs = qs.filter(DUPLICATE_WITHDRAWAL)
    review = query.get("review")
    q = (query.get("q") or "").strip()
    tracks = _many(query, "track")
    tags = _many(query, "tag")
    items = []
    for submission in qs.order_by("position", "id"):
        haystack = " ".join(
            [submission.title, submission.tagline, submission.description, " ".join(submission.tech_tags or [])]
        )
        if q and q.casefold() not in haystack.casefold():
            continue
        # Tracks: any of the chosen tracks. Tags: every chosen tag.
        if tracks and submission.track_id not in tracks and submission.track.name not in tracks:
            continue
        if tags and not set(tags) <= set(submission.tech_tags or []):
            continue
        n = per[submission.id]
        if review == "full" and n < 3:
            continue
        if review == "short" and (submission.state == "withdrawn" or n >= 3):
            continue
        badge = ""
        if submission.state == "withdrawn" and submission.withdrawn_reason.startswith("duplicate_of:"):
            badge = "withdrawn: duplicate of " + submission.withdrawn_reason.split(":", 1)[1]
        items.append(
            {
                "id": submission.id,
                "title": submission.title,
                "tagline": submission.tagline,
                "track": submission.track_id,
                "track_name": submission.track.name,
                "team_id": submission.team_id,
                "team_name": submission.team.name,
                "state": submission.state,
                "repo_url": submission.repo_url,
                "live_url": submission.live_url,
                "video_url": submission.video_url,
                "tech_tags": " ".join(submission.tech_tags or []),
                "position": submission.position,
                "n_reviews": n,
                "badge": badge,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            }
        )
    try:
        page = max(1, int(query.get("page") or 1))
    except ValueError:
        page = 1
    # HTML and JSON are paged by 50. A CSV download is the whole list.
    if paginate:
        start = (page - 1) * 50
        window = items[start : start + 50]
    else:
        page = 1
        window = items
    return {
        "title": "Projects",
        "event": event_id,
        "resource": "projects",
        "count": len(items),
        "page": page,
        "pages": max(1, (len(items) + 49) // 50) if paginate else 1,
        "columns": [
            "id",
            "title",
            "tagline",
            "track",
            "track_name",
            "team_name",
            "state",
            "n_reviews",
            "badge",
            "repo_url",
        ],
        "items": window,
        "tracks": [
            {"id": row.id, "name": row.name, "checked": row.id in tracks}
            for row in Track.objects.filter(event_id=event_id).order_by("id")
        ],
        "tags": [
            {"name": tag, "checked": tag in tags}
            for tag in sorted(
                {tag for values in qs.values_list("tech_tags", flat=True) for tag in (values or [])} | set(tags)
            )
        ],
        "download_csv": f"/e/{event_id}/projects.csv",
        "download_json": f"/e/{event_id}/projects.json",
        "html_omitted": {},
        "filters": {"q": q, "track": ",".join(tracks), "tag": ",".join(tags), "state": state or "", "review": review or "", "duplicate": "1" if duplicate else ""},
    }
