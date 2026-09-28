"""Demo seed. Fixture people get an unusable password. Six principals share one hash."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils.dateparse import parse_datetime

from samepage.apps.portal.models import (
    ApiToken,
    Assignment,
    AssignmentRun,
    Batch,
    Criterion,
    Event,
    JudgeTrack,
    Person,
    PrizeCategory,
    RoleGrant,
    ScoreRev,
    Submission,
    Team,
    TeamMember,
    Track,
)
from samepage.domain.tokens import DEMO_PASSWORD, PRINCIPALS, demo_token, token_digest
from samepage.services import audit, results
from samepage.services.duplicates import ensure_provisional

UNUSABLE = "!"


def _when(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def seed(path: str) -> bool:
    if Event.objects.filter(id="evt_01").exists():
        return False
    with transaction.atomic():
        with open(path, encoding="utf-8") as handle:
            fixture = json.load(handle)
        _event_one(fixture)
        _event_two()
        _passwords_and_tokens()
        _demo_batches(fixture)
    results.rebuild("evt_01", actor="importer")
    return True


def _event_one(fixture: dict) -> None:
    close = _when(fixture["event"]["submissions_close"])
    event = Event.objects.create(
        id="evt_01",
        name=fixture["event"]["name"],
        state="judging",
        submissions_close=close,
        windows={"submissions_close": fixture["event"]["submissions_close"]},
        blind_judging=False,
        custom_questions=[],
    )
    tracks = {
        row["id"]: Track.objects.create(id=row["id"], event=event, name=row["name"])
        for row in fixture["tracks"]
    }
    for position, key in enumerate(("functionality", "quality", "innovation")):
        Criterion.objects.create(event=event, track=None, key=key, label=key.capitalize(), weight=1, position=position)
    PrizeCategory.objects.create(id="prz_01", event=event, name="Grand prize")

    people: dict[str, Person] = {}
    for judge in fixture["judges"]:
        person = Person(
            id=judge["id"],
            email=judge["email"].lower(),
            name=judge["name"],
            password=UNUSABLE,
            is_admin=False,
        )
        people[person.email] = person
    Person.objects.bulk_create(people.values())
    for judge in fixture["judges"]:
        RoleGrant.objects.create(person_id=judge["id"], event=event, role="judge")
        for track_id in judge.get("tracks") or []:
            JudgeTrack.objects.create(person_id=judge["id"], event=event, track_id=track_id)

    teams = {}
    for row in fixture["teams"]:
        team = Team.objects.create(id=row["id"], event=event, name=row["name"])
        teams[team.id] = team
        for email in row["members"]:
            email = email.lower()
            person = people.get(email)
            if person is None:
                person_id = "per_priya1" if email == "priya1@example.org" else "mem_" + email.split("@", 1)[0].replace(".", "_")
                person = Person.objects.create(id=person_id, email=email, name=email.split("@", 1)[0], password=UNUSABLE)
                people[email] = person
            TeamMember.objects.create(event=event, team=team, person=person)
            RoleGrant.objects.get_or_create(person=person, event=event, role="participant")

    for index, row in enumerate(fixture["projects"]):
        Submission.objects.create(
            id=row["id"],
            event=event,
            team_id=row["team"],
            track_id=row["track"],
            position=index,
            title=row["title"],
            tagline=row.get("summary") or "",
            description="",
            repo_url=row.get("repo_url") or "",
            state="submitted",
            origin="import",
            submitted_at=_when(row["submitted_at"]),
            tech_tags=[],
            custom_answers={},
        )
    ensure_provisional(event.id)

    by_judge: dict[str, list] = {}
    for score in fixture["scores"]:
        by_judge.setdefault(score["judge"], []).append(score)
        seq = audit.append(
            event.id,
            "importer",
            "score.imported",
            f"{score['judge']}:{score['project']}",
            None,
            {"project": score["project"], "judge": score["judge"]},
        )
        for key, value in score["criteria"].items():
            ScoreRev.objects.create(
                judge_id=score["judge"],
                submission_id=score["project"],
                criterion=key,
                rev=1,
                value=int(value),
                state="final",
                comment=score.get("comment") or "",
                audit_seq=seq,
            )

    run = AssignmentRun.objects.create(
        id="run_import",
        event=event,
        kind="import",
        seed=0,
        params={"source": "fixtures.json"},
        report={"note": "One batch per judge, containing only the projects they scored. No invented batches."},
    )
    for judge_id, scores in by_judge.items():
        batch = Batch.objects.create(
            id=f"bat_{judge_id}",
            event=event,
            judge_id=judge_id,
            run=run,
            state="done",
        )
        seen = set()
        for score in scores:
            if score["project"] in seen:
                continue
            seen.add(score["project"])
            Assignment.objects.create(
                batch=batch,
                judge_id=judge_id,
                submission_id=score["project"],
                source="import",
                finalized_at=_when(fixture["event"]["submissions_close"]),
            )
    _staff(event)


def _staff(event: Event) -> None:
    Person.objects.create(
        id="org_01",
        email="organizer@example.org",
        name="Organizer",
        password=UNUSABLE,
    )
    Person.objects.create(
        id="adm_01",
        email="admin@example.org",
        name="Admin",
        password=UNUSABLE,
        is_admin=True,
    )
    RoleGrant.objects.create(person_id="org_01", event=event, role="organizer")
    RoleGrant.objects.create(person_id="adm_01", event=event, role="organizer")


def _event_two() -> None:
    event = Event.objects.create(
        id="evt_02",
        name="Open control",
        state="open",
        submissions_close=datetime(2027, 1, 1, tzinfo=timezone.utc),
        windows={},
        blind_judging=False,
    )
    Track.objects.create(id="trk_e2", event=event, name="Control")
    for position, key in enumerate(("functionality", "quality", "innovation")):
        Criterion.objects.create(event=event, track=None, key=key, label=key.capitalize(), weight=1, position=position)
    person = Person.objects.create(
        id="per_control",
        email="control@example.org",
        name="Control",
        password=UNUSABLE,
    )
    team = Team.objects.create(id="tm_e2", event=event, name="Control team")
    TeamMember.objects.create(event=event, team=team, person=person)
    RoleGrant.objects.create(person=person, event=event, role="participant")
    RoleGrant.objects.create(person_id="org_01", event=event, role="organizer")


def _passwords_and_tokens() -> None:
    shared = make_password(DEMO_PASSWORD)
    for slug, spec in PRINCIPALS.items():
        Person.objects.filter(id=spec["id"]).update(password=shared)
        ApiToken.objects.create(
            id=f"tok_{slug}",
            person_id=spec["id"],
            token_sha256=token_digest(demo_token(slug)),
            scopes=["demo"],
            demo=True,
        )


DEMO_JUDGES = ("jdg_08", "jdg_03")


def _demo_batches(fixture: dict) -> None:
    """Demo only: one open batch for each demo judge, so the console has something to score.

    The fixture's judges have finished (or abandoned) their batches, so on a fresh volume
    Judge A and Judge B would have nothing left to do. Each gets two projects in their own
    tracks that they have not reviewed, fewest reviews first. Nothing is scored for them.
    The run is kind "manual", named run_demo, and audited like any other assignment.
    """
    from collections import Counter

    reviews = Counter(score["project"] for score in fixture["scores"])
    scored = {(score["judge"], score["project"]) for score in fixture["scores"]}
    judge_tracks = {row["id"]: set(row.get("tracks") or []) for row in fixture["judges"]}
    projects = {row["id"]: row for row in fixture["projects"]}
    active = set(
        Submission.objects.filter(event_id="evt_01", state="submitted").values_list("id", flat=True)
    )
    run = AssignmentRun.objects.create(
        id="run_demo",
        event_id="evt_01",
        kind="manual",
        seed=0,
        params={"source": "demo seed: open work for the demo judges"},
        report={},
    )
    issued = []
    for judge_id in DEMO_JUDGES:
        candidates = sorted(
            (
                project_id
                for project_id, row in projects.items()
                if project_id in active
                and row["track"] in judge_tracks.get(judge_id, set())
                and (judge_id, project_id) not in scored
            ),
            key=lambda project_id: (reviews[project_id], project_id),
        )[:2]
        if not candidates:
            continue
        batch = Batch.objects.create(
            id=f"bat_demo_{judge_id}", event_id="evt_01", judge_id=judge_id, run=run, state="issued"
        )
        for project_id in candidates:
            Assignment.objects.create(batch=batch, judge_id=judge_id, submission_id=project_id, source="manual")
            issued.append({"project_id": project_id, "judge_id": judge_id})
    run.report = {"assignments": issued, "coi_violations": 0}
    run.save(update_fields=["report"])
    audit.append(
        "evt_01",
        "seed",
        "assignment.manual",
        run.id,
        None,
        {"assignments": [f"{row['project_id']}:{row['judge_id']}" for row in issued], "demo": True},
    )


def banner(port: int = 8080) -> str:
    base = f"http://localhost:{port}"
    lines = [
        "samepage ready",
        f"gallery {base}/e/evt_01/projects",
        f"organizer {base}/demo/enter/org",
        f"judge_a {base}/demo/enter/jdg08",
        f"judge_b {base}/demo/enter/jdg03",
        f"participant {base}/demo/enter/priya1",
        f"admin {base}/demo/enter/admin",
        f"password {DEMO_PASSWORD}",
    ]
    for slug, label in (("org", "organizer"), ("jdg08", "judge_a"), ("jdg03", "judge_b"), ("priya1", "participant")):
        lines.append(f"{label} Authorization: Bearer {demo_token(slug)}")
    return "\n".join(lines)
