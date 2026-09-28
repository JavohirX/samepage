"""Score revs, the console, and assignment runs. Identical autosaves do not insert a row."""

from __future__ import annotations

import secrets

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    Batch,
    Person,
    ScoreRev,
    Submission,
)
from samepage.core.errors import Conflict, Unprocessable
from samepage.engine.assign import assign, coi_violations, graph_report, lower_bound
from samepage.services import audit
from samepage.services.ledger import criterion_keys


def _assigned(event_id: str, judge_id: str, project_id: str) -> Assignment | None:
    return (
        Assignment.objects.filter(
            judge_id=judge_id,
            submission_id=project_id,
            submission__event_id=event_id,
        )
        .select_related("submission", "batch")
        .first()
    )


def console_payload(event_id: str, judge_id: str, project_id: str) -> dict:
    row = _assigned(event_id, judge_id, project_id)
    if row is None:
        raise PermissionDenied("You cannot do that.")
    keys = criterion_keys(event_id)
    current = {}
    comment = ""
    for rev in ScoreRev.objects.filter(judge_id=judge_id, submission_id=project_id).order_by("criterion", "-rev"):
        current.setdefault(rev.criterion, rev.value)
        if rev.comment and not comment:
            comment = rev.comment
    return {
        "title": row.submission.title,
        "event": event_id,
        "resource": "console",
        "project_id": project_id,
        "tagline": row.submission.tagline,
        "track": row.submission.track_id,
        "criteria": [{"key": key, "value": current.get(key, "")} for key in keys],
        "comment": comment,
        "finalized": bool(row.finalized_at),
        "columns": ["key", "value"],
        "items": [{"key": key, "value": current.get(key, "")} for key in keys],
        "count": len(keys),
        "html_omitted": {"panel_totals": "judges do not see the weighted total while scoring"},
        "download_json": f"/e/{event_id}/judge/assignments/{project_id}.json",
    }


def _latest_map(judge_id: str, project_id: str) -> dict[str, ScoreRev]:
    found = {}
    for rev in ScoreRev.objects.filter(judge_id=judge_id, submission_id=project_id).order_by("criterion", "-rev"):
        found.setdefault(rev.criterion, rev)
    return found


@transaction.atomic
def save_scores(event_id: str, judge: Person, project_id: str, body: dict, *, final: bool) -> dict:
    row = _assigned(event_id, judge.id, project_id)
    if row is None:
        raise PermissionDenied("You cannot do that.")
    # One writer per assignment: concurrent autosaves queue here instead of racing for the next rev.
    row = Assignment.objects.select_for_update().select_related("submission", "batch").get(pk=row.pk)
    if row.finalized_at and not final:
        raise Conflict("This score is final.")
    keys = criterion_keys(event_id)
    incoming = body.get("criteria") or body
    if not isinstance(incoming, dict):
        raise Unprocessable({"criteria": "Expected an object of criterion scores."})
    comment = body.get("comment") or ""
    if not isinstance(comment, str):
        raise Unprocessable({"comment": "Expected text."})
    values = {}
    errors = {}
    for key in keys:
        raw = incoming.get(key, body.get(f"c_{key}"))
        if raw in (None, ""):
            errors[key] = "Score from 1 to 5."
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            errors[key] = "Score from 1 to 5."
            continue
        if number < 1 or number > 5:
            errors[key] = "Score from 1 to 5."
            continue
        values[key] = number
    if errors:
        raise Unprocessable(errors)
    state = "final" if final else "draft"
    latest = _latest_map(judge.id, project_id)
    unchanged = all(
        key in latest
        and latest[key].value == values[key]
        and (latest[key].comment or "") == comment
        and latest[key].state == state
        for key in keys
    )
    if unchanged:
        return {"saved": False, "state": state, "rev": max(item.rev for item in latest.values())}
    if row.finalized_at:
        # A final score changes only through an unlock, which this build does not offer.
        raise Conflict("This score is final.")
    seq = audit.append(
        event_id,
        judge.id,
        "score.final" if final else "score.draft",
        project_id,
        None,
        {"criteria": values, "state": state},
    )
    for key in keys:
        previous = latest.get(key)
        ScoreRev.objects.create(
            judge=judge,
            submission_id=project_id,
            criterion=key,
            rev=(previous.rev + 1) if previous else 1,
            value=values[key],
            state=state,
            comment=comment,
            audit_seq=seq,
        )
    if final:
        row.finalized_at = timezone.now()
        row.save(update_fields=["finalized_at"])
        batch = row.batch
        if batch.state == "issued":
            batch.state = "in_progress"
            batch.save(update_fields=["state"])
        if not Assignment.objects.filter(batch=batch, finalized_at__isnull=True).exists():
            batch.state = "done"
            batch.save(update_fields=["state"])
    elif row.batch.state == "issued":
        row.batch.state = "in_progress"
        row.batch.save(update_fields=["state"])
    return {"saved": True, "state": state, "audit_seq": seq}


def my_batches(event_id: str, judge_id: str) -> dict:
    rows = (
        Assignment.objects.filter(judge_id=judge_id, submission__event_id=event_id)
        .select_related("submission", "batch")
        .order_by("submission__position")
    )
    items = [
        {
            "project_id": row.submission_id,
            "title": row.submission.title,
            "track": row.submission.track_id,
            "batch_id": row.batch_id,
            "finalized": "true" if row.finalized_at else "false",
        }
        for row in rows
    ]
    return {
        "title": "Your batches",
        "event": event_id,
        "resource": "judge-batches",
        "columns": ["project_id", "title", "track", "batch_id", "finalized"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/judge/batches.csv",
        "download_json": f"/e/{event_id}/judge/batches.json",
        "html_omitted": {},
    }


def _pools(event_id: str, *, include_withdrawn: bool = False):
    from samepage.apps.portal.models import Coi, JudgeTrack, TeamMember

    projects = []
    submissions = Submission.objects.filter(event_id=event_id).select_related("team")
    if not include_withdrawn:
        submissions = submissions.exclude(state="withdrawn")
    for submission in submissions:
        emails = list(
            TeamMember.objects.filter(team_id=submission.team_id).values_list("person__email", flat=True)
        )
        projects.append(
            {
                "id": submission.id,
                "track": submission.track_id,
                "team": submission.team_id,
                "team_emails": emails,
            }
        )
    judges = []
    people = Person.objects.filter(grants__event_id=event_id, grants__role="judge").distinct()
    for person in people:
        tracks = list(JudgeTrack.objects.filter(person=person, event_id=event_id).values_list("track_id", flat=True))
        coi = list(Coi.objects.filter(judge=person).values_list("team_id", flat=True))
        judges.append({"id": person.id, "tracks": tracks, "email": person.email, "coi_teams": coi})
    existing = set(
        Assignment.objects.filter(submission__event_id=event_id).values_list("submission_id", "judge_id")
    )
    return projects, judges, existing


def _conflicts(event_id: str, pairs) -> list[dict]:
    projects, judges, _existing = _pools(event_id, include_withdrawn=True)
    return coi_violations(pairs, projects, judges)


@transaction.atomic
def dry_run(event_id: str, *, actor: str, seed: int = 20260301, cap: int = 12, coverage: int = 3) -> dict:
    projects, judges, _existing = _pools(event_id)
    # A fresh design ignores the imported reviews, which is what the dry-run button is for.
    report = assign(projects, judges, existing=set(), cap=cap, coverage=coverage, seed=seed)
    edges = [(row["project_id"], row["judge_id"]) for row in report["assignments"]]
    graph = graph_report(edges)
    bound = lower_bound(projects, judges, coverage=coverage)
    run = AssignmentRun.objects.create(
        id="run_" + secrets.token_hex(4),
        event_id=event_id,
        kind="dry_run",
        seed=seed,
        params={"cap": cap, "coverage": coverage},
        report={
            **{key: report[key] for key in ("load_histogram", "achieved_max_load", "covered", "projects", "cap", "coverage")},
            "assignments": len(report["assignments"]),
            "components": graph["components"],
            "articulation_judges": graph["articulation_judges"],
            "lower_bound": bound,
            "load": report["load"],
            "coi_violations": len(coi_violations(edges, projects, judges)),
        },
    )
    audit.append(
        event_id,
        actor,
        "assignment.dry_run",
        run.id,
        None,
        {"seed": seed, "cap": cap, "coverage": coverage, "assignments": len(edges), "issued": False},
    )
    return run_payload(run)


def _run_conflicts(run: AssignmentRun, report: dict):
    if "coi_violations" in report:
        return report["coi_violations"]
    # Issued runs (the import, older top-ups): measure the assignments that exist.
    pairs = Assignment.objects.filter(batch__run=run).values_list("submission_id", "judge_id")
    return len(_conflicts(run.event_id, list(pairs)))


def run_payload(run: AssignmentRun) -> dict:
    report = run.report or {}
    items = [
        {"key": "kind", "value": run.kind},
        {"key": "seed", "value": run.seed},
        {"key": "achieved_max_load", "value": report.get("achieved_max_load", "")},
        {"key": "covered", "value": report.get("covered", "")},
        {"key": "projects", "value": report.get("projects", "")},
        {"key": "components", "value": report.get("components", "")},
        {"key": "articulation_judges", "value": " ".join(report.get("articulation_judges") or [])},
        {"key": "coi_violations", "value": _run_conflicts(run, report)},
    ]
    return {
        "title": f"Assignment {run.id}",
        "event": run.event_id,
        "resource": "assignment-run",
        "id": run.id,
        "kind": run.kind,
        "report": report,
        "columns": ["key", "value"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{run.event_id}/assignment-runs/{run.id}.csv",
        "download_json": f"/e/{run.event_id}/assignment-runs/{run.id}.json",
        "html_omitted": {},
    }


@transaction.atomic
def topup(event_id: str, *, actor: str, seed: int = 7) -> AssignmentRun:
    projects, judges, existing = _pools(event_id)
    short = []
    from collections import Counter

    counts = Counter(project for project, _judge in existing)
    for project in projects:
        if counts[project["id"]] < 3:
            short.append(project)
    report = assign(
        short or projects,
        judges,
        existing=existing,
        cap=12,
        coverage=3,
        seed=seed,
        extra_per_judge=1,
    )
    run = AssignmentRun.objects.create(
        id="run_" + secrets.token_hex(4),
        event_id=event_id,
        kind="topup",
        seed=seed,
        params={"extra_per_judge": 1},
        report={
            "assignments": report["assignments"],
            "achieved_max_load": report["achieved_max_load"],
            "load_histogram": report["load_histogram"],
            "short": sorted(row["id"] for row in short),
            "coi_violations": len(
                coi_violations(
                    [(row["project_id"], row["judge_id"]) for row in report["assignments"]], projects, judges
                )
            ),
        },
    )
    audit.append(
        event_id,
        actor,
        "assignment.topup",
        run.id,
        None,
        {
            "seed": seed,
            "short": sorted(row["id"] for row in short),
            "assignments": [f"{row['project_id']}:{row['judge_id']}" for row in report["assignments"]],
        },
    )
    by_judge: dict[str, list[str]] = {}
    for row in report["assignments"]:
        by_judge.setdefault(row["judge_id"], []).append(row["project_id"])
    for judge_id, project_ids in by_judge.items():
        batch = Batch.objects.create(
            id="bat_" + secrets.token_hex(3),
            event_id=event_id,
            judge_id=judge_id,
            run=run,
            state="issued",
        )
        for project_id in project_ids:
            Assignment.objects.create(
                batch=batch,
                judge_id=judge_id,
                submission_id=project_id,
                source="topup",
            )
    return run


@transaction.atomic
def abandon(event_id: str, batch_id: str, actor: str) -> Batch:
    batch = Batch.objects.select_for_update().filter(event_id=event_id, id=batch_id).first()
    if batch is None:
        raise NotFound("Unknown batch.")
    from samepage.domain.transitions import transition

    transition("batch", batch.state, "abandoned")
    batch.state = "abandoned"
    batch.save(update_fields=["state"])
    audit.append(event_id, actor, "batch.abandon", batch.id, None, {"state": "abandoned"})
    return batch
