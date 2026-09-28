"""Score revs, the console, and assignment runs. Identical autosaves do not insert a row."""

from __future__ import annotations

import secrets

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    Batch,
    Coi,
    JudgeTrack,
    Person,
    RoleGrant,
    ScoreCurrent,
    ScoreRev,
    Submission,
    TeamMember,
)
from samepage.core.errors import Conflict, Unprocessable
from samepage.engine.assign import assign, coi_violations, graph_report, lower_bound
from samepage.services import audit
from samepage.services.clock import db_now
from samepage.services.guards import refuse_if_published
from samepage.services.ledger import criterion_keys

# Only these states are judged. A draft is not finished and a withdrawn project is out.
JUDGED_STATES = ("submitted", "locked")


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


def _stamp_or_blank(value) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else ""


def console_payload(event_id: str, judge_id: str, project_id: str) -> dict:
    row = _assigned(event_id, judge_id, project_id)
    if row is None:
        raise PermissionDenied("You cannot do that.")
    keys = criterion_keys(event_id)
    from samepage.apps.portal.models import Criterion

    labels = {
        row.key: row.label or row.key
        for row in Criterion.objects.filter(event_id=event_id, track__isnull=True)
    }
    current = {}
    comment = ""
    state = ""
    for rev in ScoreRev.objects.filter(judge_id=judge_id, submission_id=project_id).order_by("criterion", "-rev"):
        current.setdefault(rev.criterion, rev.value)
        state = state or rev.state
        if rev.comment and not comment:
            comment = rev.comment
    submission = row.submission
    return {
        "title": submission.title,
        "event": event_id,
        "resource": "console",
        "project_id": project_id,
        "tagline": submission.tagline,
        "description": submission.description,
        "repo_url": submission.repo_url,
        "live_url": submission.live_url,
        "video_url": submission.video_url,
        "track": submission.track_id,
        "criteria": [{"key": key, "label": labels.get(key, key), "value": current.get(key, "")} for key in keys],
        "comment": comment,
        "state": state or "unscored",
        "batch_state": row.batch.state,
        "finalized": bool(row.finalized_at),
        "judging_ends": _stamp_or_blank(judging_ends(event_id)),
        "columns": ["key", "value"],
        "items": [{"key": key, "value": current.get(key, "")} for key in keys],
        "count": len(keys),
        "html_omitted": {"panel_totals": "judges do not see the weighted total while scoring"},
        "download_json": f"/e/{event_id}/judge/assignments/{project_id}.json",
    }


def judging_ends(event_id: str):
    from samepage.apps.portal.models import Event

    return Event.objects.filter(id=event_id).values_list("judging_ends", flat=True).first()


def refuse_after_judging_ends(event_id: str) -> None:
    """The event's 'Judging ends' time, on the database clock. Unset means no end. An organizer
    reopens judging by moving the time later on the settings page (until publish)."""
    ends = judging_ends(event_id)
    if ends is not None and db_now() > ends:
        from samepage.services.events import stamp

        raise Conflict(
            f"Judging ended at {stamp(ends)} UTC. An organizer can move 'Judging ends' later on the settings page."
        )


def _latest_map(judge_id: str, project_id: str) -> dict[str, ScoreRev]:
    found = {}
    for rev in ScoreRev.objects.filter(judge_id=judge_id, submission_id=project_id).order_by("criterion", "-rev"):
        found.setdefault(rev.criterion, rev)
    return found


def _whole_score(raw) -> int | None:
    """A JSON integer or a form's digit string. true, 1.5 and "1.5" are refused, never rounded to 1."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if text.isascii() and text.isdigit():
            return int(text)
    return None


@transaction.atomic
def save_scores(event_id: str, judge: Person, project_id: str, body: dict, *, final: bool) -> dict:
    row = _assigned(event_id, judge.id, project_id)
    if row is None:
        raise PermissionDenied("You cannot do that.")
    refuse_if_published(event_id)
    refuse_after_judging_ends(event_id)
    # One writer per assignment: concurrent autosaves queue here instead of racing for the next rev.
    row = Assignment.objects.select_for_update().select_related("submission", "batch").get(pk=row.pk)
    if row.finalized_at and not final:
        raise Conflict("This score is final.")
    if row.batch.state == "abandoned" and not row.finalized_at:
        raise Conflict("The organizer abandoned this batch; the project was handed to another judge.")
    if row.submission.state not in JUDGED_STATES:
        raise Conflict(f"This project is {row.submission.state} and is not being judged.")
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
        number = _whole_score(raw)
        if number is None or number < 1 or number > 5:
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
        # A final score changes only after an organizer unlocks it (POST .../unlock, audited).
        raise Conflict("This score is final. An organizer can unlock it.")
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
        # Work still to do first, then the finished reviews.
        .order_by(F("finalized_at").asc(nulls_first=True), "submission__position", "submission_id")
    )
    drafts = set(
        ScoreCurrent.objects.filter(judge_id=judge_id, submission__event_id=event_id, state="draft").values_list(
            "submission_id", flat=True
        )
    )
    items = [
        {
            "project_id": row.submission_id,
            "title": row.submission.title,
            "track": row.submission.track_id,
            "batch_id": row.batch_id,
            "batch_state": row.batch.state,
            "finalized": "true" if row.finalized_at else "false",
            "status": "final" if row.finalized_at else ("draft saved" if row.submission_id in drafts else "to score"),
        }
        for row in rows
    ]
    return {
        "title": "Your batches",
        "event": event_id,
        "resource": "judge-batches",
        "open": sum(1 for item in items if item["finalized"] == "false" and item["batch_state"] != "abandoned"),
        "columns": ["project_id", "title", "track", "batch_id", "batch_state", "finalized", "status"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/judge/batches.csv",
        "download_json": f"/e/{event_id}/judge/batches.json",
        "html_omitted": {},
    }


def _pools(event_id: str, *, include_withdrawn: bool = False):
    """Projects being judged and the event's judges, both in id order, so a run with a seed is reproducible."""
    projects = []
    submissions = Submission.objects.filter(event_id=event_id).select_related("team").order_by("id")
    if include_withdrawn:
        submissions = submissions.exclude(state="draft")
    else:
        submissions = submissions.filter(state__in=JUDGED_STATES)
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
    people = Person.objects.filter(grants__event_id=event_id, grants__role="judge").distinct().order_by("id")
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


def _run_params(body: dict) -> dict:
    """cap, coverage and seed from a form or JSON. Whole numbers in a sane range, else 422."""
    limits = {"cap": (1, 60, 12), "coverage": (1, 10, 3), "seed": (0, 2**31 - 1, None)}
    found = {}
    for key, (low, high, default) in limits.items():
        raw = body.get(key)
        if raw in (None, ""):
            if default is not None:
                found[key] = default
            continue
        if isinstance(raw, bool):
            raise Unprocessable({key: f"A whole number from {low} to {high}."})
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise Unprocessable({key: f"A whole number from {low} to {high}."}) from None
        if not low <= value <= high:
            raise Unprocessable({key: f"A whole number from {low} to {high}."})
        found[key] = value
    return found


def _active_pairs(event_id: str) -> tuple[set[tuple[str, str]], set[str]]:
    """Pairs that still count toward coverage, and judges whose batch was abandoned.

    An abandoned batch's unfinished assignments do not count, so its projects are topped up again,
    and its judge gets no new work from a run.
    """
    active = set()
    abandoned_judges = set()
    for project, judge, finalized, state in Assignment.objects.filter(submission__event_id=event_id).values_list(
        "submission_id", "judge_id", "finalized_at", "batch__state"
    ):
        if state == "abandoned" and finalized is None:
            abandoned_judges.add(judge)
            continue
        active.add((project, judge))
    return active, abandoned_judges


def _issue(event_id: str, run: AssignmentRun, pairs: list[tuple[str, str]], source: str) -> list[dict]:
    """Batches, one per judge, for the pairs. A pair that already exists is skipped, never duplicated."""
    taken = set(Assignment.objects.filter(submission__event_id=event_id).values_list("submission_id", "judge_id"))
    by_judge: dict[str, list[str]] = {}
    issued = []
    for project_id, judge_id in pairs:
        if (project_id, judge_id) in taken:
            continue
        taken.add((project_id, judge_id))
        by_judge.setdefault(judge_id, []).append(project_id)
        issued.append({"project_id": project_id, "judge_id": judge_id})
    for judge_id in sorted(by_judge):
        batch = Batch.objects.create(
            id="bat_" + secrets.token_hex(4),
            event_id=event_id,
            judge_id=judge_id,
            run=run,
            state="issued",
        )
        for project_id in by_judge[judge_id]:
            Assignment.objects.create(batch=batch, judge_id=judge_id, submission_id=project_id, source=source)
    return issued


@transaction.atomic
def initial(event_id: str, *, actor: str, body: dict | None = None) -> AssignmentRun:
    """Issue batches so every judged project reaches `coverage` reviews, counting what is already assigned."""
    refuse_if_published(event_id)
    params = _run_params(body or {})
    seed = params.get("seed", 20260301)
    projects, judges, _existing = _pools(event_id)
    active, abandoned_judges = _active_pairs(event_id)
    report = assign(
        projects,
        judges,
        existing=active,
        cap=params["cap"],
        coverage=params["coverage"],
        seed=seed,
        abandoned=abandoned_judges,
    )
    edges = [(row["project_id"], row["judge_id"]) for row in report["assignments"]]
    run = AssignmentRun.objects.create(
        id="run_" + secrets.token_hex(4),
        event_id=event_id,
        kind="initial",
        seed=seed,
        params={"cap": params["cap"], "coverage": params["coverage"]},
        report={},
    )
    issued = _issue(event_id, run, edges, "initial")
    run.report = {
        "assignments": issued,
        "achieved_max_load": report["achieved_max_load"],
        "load_histogram": report["load_histogram"],
        "covered": report["covered"],
        "projects": report["projects"],
        "cap": params["cap"],
        "coverage": params["coverage"],
        "coi_violations": len(coi_violations([(r["project_id"], r["judge_id"]) for r in issued], projects, judges)),
    }
    run.save(update_fields=["report"])
    audit.append(
        event_id,
        actor,
        "assignment.initial",
        run.id,
        None,
        {
            "seed": seed,
            "cap": params["cap"],
            "coverage": params["coverage"],
            "assignments": [f"{row['project_id']}:{row['judge_id']}" for row in issued],
        },
    )
    return run


@transaction.atomic
def manual(event_id: str, *, actor: str, body: dict) -> AssignmentRun:
    """Assign one judge to one project by hand. The rules the matcher follows are enforced here too."""
    refuse_if_published(event_id)
    judge_id = body.get("judge") or body.get("judge_id")
    project_id = body.get("project") or body.get("project_id")
    if not isinstance(judge_id, str) or not judge_id:
        raise Unprocessable({"judge": "Choose a judge of this event."})
    if not isinstance(project_id, str) or not project_id:
        raise Unprocessable({"project": "Choose a project of this event."})
    if not RoleGrant.objects.filter(event_id=event_id, person_id=judge_id, role="judge").exists():
        raise Unprocessable({"judge": f"{judge_id} is not a judge of this event."})
    submission = Submission.objects.filter(event_id=event_id, id=project_id).select_related("team").first()
    if submission is None:
        raise Unprocessable({"project": f"{project_id} is not a project of this event."})
    if submission.state not in JUDGED_STATES:
        raise Conflict(f"{project_id} is {submission.state}; only submitted projects are judged.")
    if not JudgeTrack.objects.filter(event_id=event_id, person_id=judge_id, track_id=submission.track_id).exists():
        raise Conflict(f"{judge_id} does not judge the track {submission.track_id}.")
    judge = Person.objects.get(id=judge_id)
    on_team = TeamMember.objects.filter(team_id=submission.team_id, person__email=judge.email).exists()
    if on_team or Coi.objects.filter(judge_id=judge_id, team_id=submission.team_id).exists():
        raise Conflict(f"{judge_id} has a conflict of interest with {project_id}'s team.")
    if Assignment.objects.filter(judge_id=judge_id, submission_id=project_id).exists():
        raise Conflict(f"{judge_id} is already assigned {project_id}.")
    run = AssignmentRun.objects.create(
        id="run_" + secrets.token_hex(4),
        event_id=event_id,
        kind="manual",
        seed=0,
        params={"by": actor},
        report={},
    )
    issued = _issue(event_id, run, [(project_id, judge_id)], "manual")
    # The checks above refuse a conflicted pair; the run page still measures it from the pair.
    run.report = {"assignments": issued}
    run.save(update_fields=["report"])
    audit.append(event_id, actor, "assignment.manual", run.id, None, {"assignments": [f"{project_id}:{judge_id}"]})
    return run


@transaction.atomic
def unlock(event_id: str, *, actor: str, judge_id: str, project_id: str, body: dict) -> dict:
    """Reopen a finalized score so the judge can correct it. The trigger insists on this audit row."""
    refuse_if_published(event_id)
    row = (
        Assignment.objects.select_for_update()
        .filter(judge_id=judge_id, submission_id=project_id, submission__event_id=event_id)
        .select_related("batch")
        .first()
    )
    if row is None:
        raise NotFound("No such assignment.")
    if row.finalized_at is None:
        raise Conflict("This score is not final, so there is nothing to unlock.")
    reason = body.get("reason") or ""
    if not isinstance(reason, str) or len(reason) > 500:
        raise Unprocessable({"reason": "Text of at most 500 characters."})
    latest = _latest_map(judge_id, project_id)
    seq = audit.append(
        event_id,
        actor,
        "score.unlock",
        f"{judge_id}:{project_id}",
        {"state": "final", "criteria": {key: rev.value for key, rev in latest.items()}},
        {"state": "unlocked", "reason": reason.strip()},
    )
    for key, previous in latest.items():
        ScoreRev.objects.create(
            judge_id=judge_id,
            submission_id=project_id,
            criterion=key,
            rev=previous.rev + 1,
            value=previous.value,
            state="unlocked",
            comment=previous.comment,
            audit_seq=seq,
        )
    row.finalized_at = None
    row.save(update_fields=["finalized_at"])
    if row.batch.state == "done":
        row.batch.state = "in_progress"
        row.batch.save(update_fields=["state"])
    return {"unlocked": f"{judge_id}:{project_id}", "audit_seq": seq}


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
            # A dry run issues nothing, so it keeps the count. Only a top-up lists the pairs it issued.
            "n_assignments": len(report["assignments"]),
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


def _issued_pairs(report: dict) -> list[dict]:
    """The pairs a top-up issued. Dry runs stored before n_assignments existed keep a bare count here."""
    pairs = report.get("assignments")
    return pairs if isinstance(pairs, list) else []


def _assignment_count(report: dict):
    if "n_assignments" in report:
        return report["n_assignments"]
    pairs = report.get("assignments")
    if isinstance(pairs, list):
        return len(pairs)
    return pairs if isinstance(pairs, int) else ""


def run_payload(run: AssignmentRun) -> dict:
    report = run.report or {}
    items = [
        {"key": "kind", "value": run.kind},
        {"key": "seed", "value": run.seed},
        {"key": "assignments", "value": _assignment_count(report)},
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
        "issued_pairs": _issued_pairs(report),
        "columns": ["key", "value"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{run.event_id}/assignment-runs/{run.id}.csv",
        "download_json": f"/e/{run.event_id}/assignment-runs/{run.id}.json",
        "html_omitted": {},
    }


@transaction.atomic
def topup(event_id: str, *, actor: str, seed: int = 7) -> AssignmentRun:
    refuse_if_published(event_id)
    projects, judges, _existing = _pools(event_id)
    existing, abandoned_judges = _active_pairs(event_id)
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
        abandoned=abandoned_judges,
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
    _issue(event_id, run, [(row["project_id"], row["judge_id"]) for row in report["assignments"]], "topup")
    return run


@transaction.atomic
def abandon(event_id: str, batch_id: str, actor: str) -> Batch:
    refuse_if_published(event_id)
    batch = Batch.objects.select_for_update().filter(event_id=event_id, id=batch_id).first()
    if batch is None:
        raise NotFound("Unknown batch.")
    from samepage.domain.transitions import transition

    transition("batch", batch.state, "abandoned")
    batch.state = "abandoned"
    batch.save(update_fields=["state"])
    audit.append(event_id, actor, "batch.abandon", batch.id, None, {"state": "abandoned"})
    return batch


def assignments_payload(event_id: str) -> dict:
    """Every judge-project pair with its batch, source and state: the assignment ledger as CSV or JSON."""
    rows = (
        Assignment.objects.filter(submission__event_id=event_id)
        .select_related("batch", "submission")
        .order_by("judge_id", "submission_id")
    )
    drafts = set(
        ScoreCurrent.objects.filter(submission__event_id=event_id, state="draft").values_list("judge_id", "submission_id")
    )
    items = []
    for row in rows:
        if row.finalized_at:
            status = "final"
        elif row.batch.state == "abandoned":
            status = "abandoned"
        elif (row.judge_id, row.submission_id) in drafts:
            status = "draft"
        else:
            status = "open"
        items.append(
            {
                "judge_id": row.judge_id,
                "project_id": row.submission_id,
                "track": row.submission.track_id,
                "batch_id": row.batch_id,
                "run_id": row.batch.run_id,
                "source": row.source,
                "status": status,
                "finalized_at": row.finalized_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.finalized_at else "",
            }
        )
    return {
        "title": "Assignments",
        "event": event_id,
        "resource": "assignments",
        "columns": ["judge_id", "project_id", "track", "batch_id", "run_id", "source", "status", "finalized_at"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/assignments.csv",
        "download_json": f"/e/{event_id}/assignments.json",
        "html_omitted": {},
    }


def judge_progress(event_id: str) -> list[dict]:
    """One row per judge: assigned, finalized, drafts, open. Open work first, so delinquent judges lead."""
    totals: dict[str, dict] = {}
    names = dict(
        Person.objects.filter(grants__event_id=event_id, grants__role="judge").values_list("id", "name")
    )
    for judge_id in names:
        totals[judge_id] = {"assigned": 0, "finalized": 0, "abandoned": 0}
    for judge_id, finalized, state in Assignment.objects.filter(submission__event_id=event_id).values_list(
        "judge_id", "finalized_at", "batch__state"
    ):
        entry = totals.setdefault(judge_id, {"assigned": 0, "finalized": 0, "abandoned": 0})
        entry["assigned"] += 1
        if finalized is not None:
            entry["finalized"] += 1
        elif state == "abandoned":
            entry["abandoned"] += 1
    drafts: dict[str, int] = {}
    for judge_id, _project in set(
        ScoreCurrent.objects.filter(submission__event_id=event_id, state="draft").values_list("judge_id", "submission_id")
    ):
        drafts[judge_id] = drafts.get(judge_id, 0) + 1
    rows = []
    for judge_id, entry in totals.items():
        open_count = entry["assigned"] - entry["finalized"] - entry["abandoned"]
        rows.append(
            {
                "judge_id": judge_id,
                "name": names.get(judge_id, ""),
                "assigned": entry["assigned"],
                "finalized": entry["finalized"],
                "open": open_count,
                "abandoned": entry["abandoned"],
                "drafts": drafts.get(judge_id, 0),
                "behind": "true" if open_count > 0 else "false",
            }
        )
    rows.sort(key=lambda row: (-row["open"], row["judge_id"]))
    return rows
