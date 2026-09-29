"""Bundle import and export service (S13).

A JSON event bundle that is a strict superset of fixtures.json format.
Round-trip export -> import -> same results hash.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    Batch,
    Criterion,
    Event,
    JudgeTrack,
    Person,
    ResultsSnapshot,
    RoleGrant,
    ScoreCurrent,
    ScoreRev,
    Submission,
    Team,
    TeamMember,
    Track,
    VotingConfig,
)
from samepage.services import audit, results


def export_event_bundle(event: Event) -> dict[str, Any]:
    """Export complete event as a JSON document that is a superset of fixtures.json."""
    tracks = list(Track.objects.filter(event=event).order_by("id"))
    judges = list(
        Person.objects.filter(grants__event=event, grants__role="judge")
        .distinct()
        .order_by("id")
    )
    teams = list(Team.objects.filter(event=event).prefetch_related("members__person").order_by("id"))
    submissions = list(Submission.objects.filter(event=event).order_by("id"))
    criteria = list(Criterion.objects.filter(event=event).order_by("position", "id"))

    # Gather tracks per judge
    judge_tracks = {}
    for jt in JudgeTrack.objects.filter(event=event):
        judge_tracks.setdefault(jt.person_id, []).append(jt.track_id)

    # Gather scores
    scores_rows = []
    reviews = (
        ScoreCurrent.objects.filter(submission__event=event, state="final")
        .select_related("judge", "submission")
        .order_by("submission_id", "judge_id", "criterion")
    )
    for r in reviews:
        scores_rows.append({
            "judge_id": r.judge_id,
            "project_id": r.submission_id,
            "criterion": r.criterion,
            "score": int(r.value),
            "comment": r.comment,
        })

    snapshot = ResultsSnapshot.objects.filter(event=event).order_by("-seq").first()

    bundle = {
        "event": {
            "id": event.id,
            "name": event.name,
            "submissions_close": event.submissions_close.isoformat() if event.submissions_close else None,
            "state": event.state,
        },
        "tracks": [{"id": t.id, "name": t.name} for t in tracks],
        "judges": [
            {
                "id": j.id,
                "name": j.name,
                "email": j.email,
                "tracks": sorted(judge_tracks.get(j.id, [])),
            }
            for j in judges
        ],
        "teams": [
            {
                "id": t.id,
                "name": t.name,
                "members": [
                    {"id": m.person.id, "email": m.person.email, "name": m.person.name}
                    for m in t.members.all()
                ],
            }
            for t in teams
        ],
        "projects": [
            {
                "id": s.id,
                "title": s.title,
                "tagline": s.tagline,
                "track": s.track_id,
                "team": s.team_id,
                "team_id": s.team_id,
                "state": s.state,
                "withdrawn_reason": s.withdrawn_reason,
                "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
            }
            for s in submissions
        ],
        "scores": scores_rows,
        # Superset fields:
        "criteria": [
            {
                "key": c.key,
                "label": c.label,
                "weight": float(c.weight),
                "position": c.position,
                "track_id": c.track_id,
            }
            for c in criteria
        ],
        "results_hash": snapshot.ranking_sha256 if snapshot else "",
    }
    return bundle


def import_event_bundle(
    bundle: dict[str, Any],
    new_event_id: str = "",
    actor: str = "importer",
) -> tuple[Event, dict[str, int]]:
    """Import a fixtures.json or Samepage bundle into a new event.

    Returns (event, {"read": N, "written": M, "rejected": K})
    """
    evt_data = bundle.get("event") or {}
    base_id = new_event_id or evt_data.get("id") or f"evt_{secrets.token_hex(4)}"

    # If ID already exists, allocate unique
    event_id = base_id
    if Event.objects.filter(id=event_id).exists():
        event_id = f"{base_id}_{secrets.token_hex(3)}"

    sub_close_raw = evt_data.get("submissions_close")
    sub_close = parse_datetime(sub_close_raw) if sub_close_raw else timezone.now()
    if sub_close and sub_close.tzinfo is None:
        sub_close = sub_close.replace(tzinfo=timezone.utc)

    stats = {"read": 0, "written": 0, "rejected": 0}

    with transaction.atomic():
        # Temporarily allow importing past submissions deadline trigger
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED;")

        event = Event.objects.create(
            id=event_id,
            name=evt_data.get("name") or "Imported Event",
            state="judging",
            submissions_close=sub_close,
            windows={"submissions_close": sub_close.isoformat() if sub_close else ""},
            blind_judging=False,
            custom_questions=[],
        )
        stats["written"] += 1

        # 1. Tracks
        tracks_data = bundle.get("tracks") or []
        stats["read"] += len(tracks_data)
        tracks_map = {}
        for trk in tracks_data:
            tid = trk.get("id")
            tname = trk.get("name", "")
            track_id = tid if tid and not Track.objects.filter(id=tid).exists() else f"{event_id}_{tid}"
            t_obj = Track.objects.create(id=track_id if tid else None, event=event, name=tname)
            tracks_map[tid] = t_obj
            stats["written"] += 1

        # 2. Criteria
        crit_data = bundle.get("criteria")
        if crit_data:
            stats["read"] += len(crit_data)
            for c in crit_data:
                Criterion.objects.create(
                    event=event,
                    track=tracks_map.get(c.get("track_id")),
                    key=c.get("key"),
                    label=c.get("label", c.get("key")),
                    weight=c.get("weight", 1.0),
                    position=c.get("position", 0),
                )
                stats["written"] += 1
        else:
            # Default standard criteria if not provided
            for pos, k in enumerate(("functionality", "quality", "innovation")):
                Criterion.objects.create(
                    event=event,
                    track=None,
                    key=k,
                    label=k.capitalize(),
                    weight=1.0,
                    position=pos,
                )
                stats["written"] += 1

        # 3. Judges
        judges_data = bundle.get("judges") or []
        stats["read"] += len(judges_data)
        judges_map = {}
        for j in judges_data:
            jid = j.get("id")
            jemail = j.get("email") or f"{jid}@example.org"
            jname = j.get("name", "")
            person, _ = Person.objects.get_or_create(email=jemail, defaults={"id": jid or jemail, "name": jname})
            RoleGrant.objects.get_or_create(event=event, person=person, role="judge")
            judges_map[jid] = person
            stats["written"] += 1

            for trk_id in j.get("tracks", []):
                if trk_id in tracks_map:
                    JudgeTrack.objects.get_or_create(event=event, person=person, track=tracks_map[trk_id])

        # 4. Teams & Members
        teams_data = bundle.get("teams") or []
        stats["read"] += len(teams_data)
        teams_map = {}
        for tm in teams_data:
            tmid = tm.get("id")
            tmname = tm.get("name", "")
            team_id = tmid if tmid and not Team.objects.filter(id=tmid).exists() else f"{event_id}_{tmid}"
            team_obj = Team.objects.create(id=team_id if tmid else None, event=event, name=tmname)
            teams_map[tmid] = team_obj
            stats["written"] += 1

            for mem in tm.get("members", []):
                if isinstance(mem, dict):
                    mid = mem.get("id")
                    memail = mem.get("email") or f"{mid}@example.org"
                    mname = mem.get("name", "")
                else:
                    mid = str(mem)
                    memail = mid if "@" in mid else f"{mid}@example.org"
                    mname = mid
                m_person, _ = Person.objects.get_or_create(email=memail, defaults={"id": mid or memail, "name": mname})
                RoleGrant.objects.get_or_create(event=event, person=m_person, role="participant")
                TeamMember.objects.create(event=event, team=team_obj, person=m_person)

        # 5. Projects / Submissions
        projects_data = bundle.get("projects") or []
        stats["read"] += len(projects_data)
        projects_map = {}
        for p in projects_data:
            pid = p.get("id")
            title = p.get("title", "")
            tagline = p.get("tagline") or p.get("summary") or ""
            trk_id = p.get("track")
            tm_id = p.get("team_id") or p.get("team")
            team_obj = teams_map.get(tm_id)
            track_obj = tracks_map.get(trk_id)

            sub_raw = p.get("submitted_at")
            if sub_raw:
                sub_time = parse_datetime(sub_raw)
                if sub_time and sub_time.tzinfo is None:
                    sub_time = sub_time.replace(tzinfo=timezone.utc)
            else:
                sub_time = sub_close if sub_close else timezone.now()
            # Set origin to import to pass submission_deadline trigger
            project_id = pid if pid and not Submission.objects.filter(id=pid).exists() else f"{event_id}_{pid}"
            sub_obj = Submission.objects.create(
                id=project_id if pid else None,
                event=event,
                team=team_obj,
                track=track_obj,
                title=title,
                tagline=tagline,
                state=p.get("state") or "submitted",
                withdrawn_reason=p.get("withdrawn_reason", ""),
                origin="import",
                submitted_at=sub_time,
            )
            projects_map[pid] = sub_obj
            stats["written"] += 1

        # 6. Scores
        scores_data = bundle.get("scores") or []
        stats["read"] += len(scores_data)

        # Build batches & assignments for scores
        # Group scores by (judge_id, project_id)
        assignments_map = {}
        crit_by_key = {c.key: c for c in Criterion.objects.filter(event=event)}

        import_run, _ = AssignmentRun.objects.get_or_create(
            id=f"run_imp_{event_id}",
            event=event,
            defaults={"kind": "import", "seed": 1, "params": {}, "report": {}},
        )

        for sc in scores_data:
            jid = sc.get("judge_id") or sc.get("judge")
            pid = sc.get("project_id") or sc.get("project")
            judge_person = judges_map.get(jid)
            sub_obj = projects_map.get(pid)
            if not judge_person or not sub_obj:
                stats["rejected"] += 1
                continue

            pair = (jid, pid)
            if pair not in assignments_map:
                batch, _ = Batch.objects.get_or_create(
                    id=f"bat_{event_id}_{jid}",
                    event=event,
                    judge=judge_person,
                    defaults={"run": import_run, "state": "done"},
                )
                asg, _ = Assignment.objects.get_or_create(
                    judge=judge_person,
                    submission=sub_obj,
                    defaults={"batch": batch, "source": "import", "finalized_at": timezone.now()},
                )
                assignments_map[pair] = asg

            seq = audit.append(
                event.id,
                actor,
                "score.imported",
                f"{jid}:{pid}",
                None,
                {"project": pid, "judge": jid},
            )

            if "criteria" in sc and isinstance(sc["criteria"], dict):
                for ck, cv in sc["criteria"].items():
                    ScoreRev.objects.create(
                        judge=judge_person,
                        submission=sub_obj,
                        criterion=ck,
                        rev=1,
                        value=int(cv),
                        state="final",
                        comment=sc.get("comment", ""),
                        audit_seq=seq,
                    )
                    stats["written"] += 1
            else:
                crit_key = sc.get("criterion")
                ScoreRev.objects.create(
                    judge=judge_person,
                    submission=sub_obj,
                    criterion=crit_key,
                    rev=1,
                    value=int(sc.get("score", 0)),
                    state="final",
                    comment=sc.get("comment", ""),
                    audit_seq=seq,
                )
                stats["written"] += 1

    # Rebuild ranking snapshot
    results.rebuild(event.id, actor=actor)
    return event, stats
