"""Events: create, edit, tracks, prizes, custom questions, the weighted rubric, state, and who judges.

Every write is audited with its before and after. Nothing that feeds the ranking changes after publish.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import (
    Assignment,
    Criterion,
    Event,
    Invite,
    JudgeTrack,
    Person,
    PrizeCategory,
    RoleGrant,
    ScoreRev,
    TeamMember,
    Track,
)
from samepage.core.errors import Conflict, Unprocessable
from samepage.domain.transitions import transition
from samepage.services import accounts, audit
from samepage.services.clock import db_now
from samepage.services.guards import refuse_if_published

DEFAULT_CRITERIA = (
    ("functionality", "Functionality"),
    ("quality", "Quality"),
    ("innovation", "Innovation"),
)
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MAX_TRACKS = 30
MAX_QUESTIONS = 20


def stamp(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- parsing ---------------------------------------------------------------------------------


def _when(body: dict, field: str, errors: dict, *, required: bool) -> datetime | None:
    raw = body.get(field)
    if raw in (None, ""):
        if required:
            errors[field] = "Required. ISO 8601 in UTC, e.g. 2026-10-01T18:00:00Z."
        return None
    if not isinstance(raw, str):
        errors[field] = "Expected an ISO 8601 date and time."
        return None
    parsed = parse_datetime(raw.strip())
    if parsed is None:
        errors[field] = "Expected an ISO 8601 date and time, e.g. 2026-10-01T18:00:00Z."
        return None
    if parsed.tzinfo is None:
        # The form's datetime-local field has no zone. Every time on this site is UTC.
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


def _lines(value) -> list[str]:
    """A JSON list of strings, or a textarea with one entry per line."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise Unprocessable({"list": "Expected a list of names, or one name per line."})


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


def _slug(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:32]
    if not key or not key[0].isalpha():
        key = ("q_" + key)[:32]
    return key


def parse_questions(value) -> list[dict]:
    """[{key, label, kind: text|choice, choices, required}], or lines "Label" / "Label: a, b, c"."""
    if value in (None, ""):
        return []
    items = []
    if isinstance(value, str):
        for line in value.splitlines():
            line = line.strip()
            if not line:
                continue
            required = line.endswith("*")
            line = line.rstrip("*").strip()
            label, sep, choices = line.partition(":")
            options = [part.strip() for part in choices.split(",") if part.strip()] if sep else []
            items.append(
                {"label": label.strip(), "kind": "choice" if options else "text", "choices": options, "required": required}
            )
    elif isinstance(value, list):
        items = value
    else:
        raise Unprocessable({"custom_questions": "Expected a list of questions."})
    questions = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise Unprocessable({"custom_questions": "Each question is an object with a label."})
        label = item.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise Unprocessable({"custom_questions": "Each question needs a label of at most 200 characters."})
        key = item.get("key") or _slug(label)
        if not isinstance(key, str) or not _KEY.match(key) or key in seen:
            raise Unprocessable({"custom_questions": f"Question keys are unique lowercase slugs ({key!r})."})
        seen.add(key)
        kind = item.get("kind") or "text"
        choices = item.get("choices") or []
        if kind not in {"text", "choice"}:
            raise Unprocessable({"custom_questions": "A question is text or choice."})
        if not isinstance(choices, list) or not all(isinstance(c, str) and c.strip() for c in choices):
            raise Unprocessable({"custom_questions": "Choices are a list of text."})
        if kind == "choice" and len(choices) < 2:
            raise Unprocessable({"custom_questions": f"The choice question {label!r} needs two choices or more."})
        questions.append(
            {
                "key": key,
                "label": label.strip(),
                "kind": kind,
                "choices": [c.strip() for c in choices] if kind == "choice" else [],
                "required": _flag(item.get("required")),
            }
        )
    if len(questions) > MAX_QUESTIONS:
        raise Unprocessable({"custom_questions": f"At most {MAX_QUESTIONS} questions."})
    return questions


def _weight(value, where: str) -> Decimal:
    try:
        weight = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise Unprocessable({where: "A weight is a positive number."}) from None
    if isinstance(value, bool) or not weight.is_finite() or weight <= 0 or weight > 1000:
        raise Unprocessable({where: "A weight is a positive number up to 1000."})
    if weight != weight.quantize(Decimal("0.0001")):
        raise Unprocessable({where: "At most four decimal places."})
    return weight


def parse_criteria(value) -> list[dict]:
    """[{key, label, weight}] or lines "key: weight" / "Label: weight"."""
    if value in (None, ""):
        return [{"key": key, "label": label, "weight": Decimal(1)} for key, label in DEFAULT_CRITERIA]
    items = []
    if isinstance(value, str):
        for line in value.splitlines():
            if not line.strip():
                continue
            label, sep, weight = line.partition(":")
            items.append({"label": label.strip(), "weight": weight.strip() if sep else "1"})
    elif isinstance(value, list):
        items = value
    else:
        raise Unprocessable({"criteria": "Expected a list of criteria."})
    criteria = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise Unprocessable({"criteria": "Each criterion is an object with a key or label and a weight."})
        label = item.get("label") or item.get("key")
        if not isinstance(label, str) or not label.strip():
            raise Unprocessable({"criteria": "Each criterion needs a key or a label."})
        key = item.get("key") or _slug(label)
        if not isinstance(key, str) or not _KEY.match(key) or key in seen:
            raise Unprocessable({"criteria": f"Criterion keys are unique lowercase slugs ({key!r})."})
        seen.add(key)
        criteria.append({"key": key, "label": label.strip()[:80], "weight": _weight(item.get("weight", 1), f"weight:{key}")})
    if not 1 <= len(criteria) <= 10:
        raise Unprocessable({"criteria": "A rubric has 1 to 10 criteria."})
    return criteria


# --- reads -----------------------------------------------------------------------------------


def criteria_rows(event_id: str) -> list[dict]:
    rows = Criterion.objects.filter(event_id=event_id).order_by("position", "key")
    base = [row for row in rows if row.track_id is None]
    overrides = {}
    for row in rows:
        if row.track_id is not None:
            overrides.setdefault(row.track_id, {})[row.key] = str(row.weight.normalize())
    return [
        {
            "key": row.key,
            "label": row.label or row.key,
            "weight": str(row.weight.normalize()),
            "track_overrides": {track: weights[row.key] for track, weights in overrides.items() if row.key in weights},
        }
        for row in base
    ]


def event_payload(event: Event, *, roles: set[str], principal) -> dict:
    tracks = [{"id": row.id, "name": row.name} for row in event.tracks.order_by("id")]
    prizes = [
        {"id": row.id, "name": row.name, "track": row.track_id or "", "description": row.description}
        for row in event.prizes.order_by("id")
    ]
    staff = bool(roles & {"organizer", "admin"})
    team = None
    if principal is not None:
        member = TeamMember.objects.filter(event=event, person=principal).select_related("team").first()
        if member is not None:
            team = {"id": member.team_id, "name": member.team.name}
    closed = db_now() > event.submissions_close
    return {
        "title": event.name,
        "event": event.id,
        "resource": "event",
        "id": event.id,
        "name": event.name,
        "description": event.description,
        "state": event.state,
        "starts_at": stamp(event.starts_at),
        "submissions_close": stamp(event.submissions_close),
        "judging_ends": stamp(event.judging_ends),
        "submissions_open": "false" if closed or event.state != "open" else "true",
        "blind_judging": "true" if event.blind_judging else "false",
        "max_team_size": event.max_team_size,
        "tracks": tracks,
        "prizes": prizes,
        "criteria": criteria_rows(event.id),
        "custom_questions": event.custom_questions or [],
        "your_roles": sorted(roles),
        "your_team": team,
        "can_manage": staff,
        "columns": ["id", "name", "state", "starts_at", "submissions_close", "judging_ends"],
        "items": [
            {
                "id": event.id,
                "name": event.name,
                "state": event.state,
                "starts_at": stamp(event.starts_at),
                "submissions_close": stamp(event.submissions_close),
                "judging_ends": stamp(event.judging_ends),
            }
        ],
        "count": 1,
        "html_omitted": {},
        "download_json": f"/e/{event.id}.json",
    }


# --- writes ----------------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _add_tracks(event: Event, names: list[str]) -> list[Track]:
    existing = {name.casefold() for name in event.tracks.values_list("name", flat=True)}
    created = []
    for name in names:
        if len(name) > 80:
            raise Unprocessable({"tracks": "A track name is at most 80 characters."})
        if name.casefold() in existing:
            continue
        existing.add(name.casefold())
        created.append(Track.objects.create(id=_new_id("trk"), event=event, name=name))
    if event.tracks.count() > MAX_TRACKS:
        raise Unprocessable({"tracks": f"At most {MAX_TRACKS} tracks."})
    return created


def _add_prizes(event: Event, names: list[str]) -> list[PrizeCategory]:
    existing = {name.casefold() for name in event.prizes.values_list("name", flat=True)}
    created = []
    for name in names:
        if len(name) > 120:
            raise Unprocessable({"prizes": "A prize name is at most 120 characters."})
        if name.casefold() in existing:
            continue
        existing.add(name.casefold())
        created.append(PrizeCategory.objects.create(id=_new_id("prz"), event=event, name=name))
    return created


def _team_size(value, errors: dict) -> int | None:
    if value in (None, ""):
        return None
    try:
        size = int(str(value).strip())
    except ValueError:
        errors["max_team_size"] = "A whole number from 1 to 20."
        return None
    if isinstance(value, bool) or not 1 <= size <= 20:
        errors["max_team_size"] = "A whole number from 1 to 20."
        return None
    return size


def _text_field(body: dict, field: str, limit: int, errors: dict, *, required: bool = False) -> str | None:
    if field not in body:
        if required:
            errors[field] = "Required."
        return None
    value = body.get(field)
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors[field] = "Expected text."
        return None
    value = value.strip()
    if required and not value:
        errors[field] = "Required."
    if len(value) > limit:
        errors[field] = f"At most {limit} characters."
    return value


def _check_windows(starts_at, close, judging_ends, errors: dict) -> None:
    if starts_at and close and starts_at >= close:
        errors["starts_at"] = "The start must be before the submission deadline."
    if judging_ends and close and judging_ends <= close:
        errors["judging_ends"] = "Judging ends after the submission deadline."


@transaction.atomic
def create(actor: Person, body: dict) -> Event:
    errors: dict = {}
    name = _text_field(body, "name", 200, errors, required=True)
    description = _text_field(body, "description", 5000, errors) or ""
    starts_at = _when(body, "starts_at", errors, required=False)
    close = _when(body, "submissions_close", errors, required=True)
    judging_ends = _when(body, "judging_ends", errors, required=False)
    _check_windows(starts_at, close, judging_ends, errors)
    size = _team_size(body.get("max_team_size"), errors)
    try:
        tracks = _lines(body.get("tracks"))
    except Unprocessable:
        errors["tracks"] = "Expected track names, one per line."
        tracks = []
    if not tracks and "tracks" not in errors:
        errors["tracks"] = "At least one track."
    try:
        prizes = _lines(body.get("prizes"))
    except Unprocessable:
        errors["prizes"] = "Expected prize names, one per line."
        prizes = []
    if errors:
        raise Unprocessable(errors)
    questions = parse_questions(body.get("custom_questions"))
    criteria = parse_criteria(body.get("criteria"))
    event = Event.objects.create(
        id=_new_id("evt"),
        name=name,
        description=description,
        state="draft",
        starts_at=starts_at,
        submissions_close=close,
        judging_ends=judging_ends,
        windows={"submissions_close": stamp(close)},
        blind_judging=_flag(body.get("blind_judging")),
        custom_questions=questions,
        max_team_size=size or 4,
        created_by=actor.id,
    )
    _add_tracks(event, tracks)
    _add_prizes(event, prizes)
    for position, row in enumerate(criteria):
        Criterion.objects.create(
            event=event, track=None, key=row["key"], label=row["label"], weight=row["weight"], position=position
        )
    RoleGrant.objects.get_or_create(person=actor, event=event, role="organizer")
    audit.append(
        event.id,
        actor.id,
        "event.create",
        event.id,
        None,
        {
            "name": event.name,
            "submissions_close": stamp(close),
            "tracks": sorted(tracks),
            "prizes": sorted(prizes),
            "criteria": {row["key"]: str(row["weight"]) for row in criteria},
        },
    )
    return event


def _settings_snapshot(event: Event) -> dict:
    return {
        "name": event.name,
        "description": event.description,
        "starts_at": stamp(event.starts_at),
        "submissions_close": stamp(event.submissions_close),
        "judging_ends": stamp(event.judging_ends),
        "blind_judging": event.blind_judging,
        "max_team_size": event.max_team_size,
        "custom_questions": event.custom_questions,
    }


@transaction.atomic
def update(event_id: str, actor: Person, body: dict) -> Event:
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    refuse_if_published(event)
    before = _settings_snapshot(event)
    errors: dict = {}
    name = _text_field(body, "name", 200, errors)
    description = _text_field(body, "description", 5000, errors)
    starts_at = _when(body, "starts_at", errors, required=False) if "starts_at" in body else event.starts_at
    close = _when(body, "submissions_close", errors, required=True) if "submissions_close" in body else event.submissions_close
    judging_ends = _when(body, "judging_ends", errors, required=False) if "judging_ends" in body else event.judging_ends
    _check_windows(starts_at, close, judging_ends, errors)
    size = _team_size(body.get("max_team_size"), errors)
    add_tracks = add_prizes = []
    try:
        add_tracks = _lines(body.get("add_tracks"))
        add_prizes = _lines(body.get("add_prizes"))
    except Unprocessable:
        errors["add_tracks"] = "Expected names, one per line."
    if errors:
        raise Unprocessable(errors)
    if name:
        event.name = name
    if description is not None:
        event.description = description
    event.starts_at = starts_at
    if close is not None:
        event.submissions_close = close
        event.windows = {**(event.windows or {}), "submissions_close": stamp(close)}
    event.judging_ends = judging_ends
    if "blind_judging" in body or body.get("form") == "settings":
        # An unticked checkbox is absent from a form post, so the settings form says which form it is.
        event.blind_judging = _flag(body.get("blind_judging"))
    if size is not None:
        event.max_team_size = size
    if "custom_questions" in body:
        event.custom_questions = parse_questions(body.get("custom_questions"))
    event.save()
    created_tracks = _add_tracks(event, add_tracks)
    created_prizes = _add_prizes(event, add_prizes)
    after = _settings_snapshot(event)
    if created_tracks:
        after["added_tracks"] = [row.name for row in created_tracks]
    if created_prizes:
        after["added_prizes"] = [row.name for row in created_prizes]
    audit.append(event.id, actor.id, "event.update", event.id, before, after)
    return event


@transaction.atomic
def set_state(event_id: str, actor: Person, target) -> Event:
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    if not isinstance(target, str) or target not in Event.STATES:
        raise Unprocessable({"state": "One of " + ", ".join(Event.STATES) + "."})
    if target == "published":
        raise Conflict("Publish from the results page, which checks duplicates and freezes the ranking.")
    transition("event", event.state, target)
    if target == "open" and not event.tracks.exists():
        raise Conflict("Add a track before opening the event.")
    if target == "closed" and db_now() <= event.submissions_close:
        raise Conflict(
            f"Submissions are open until {stamp(event.submissions_close)}. Move the deadline earlier to close now."
        )
    before = event.state
    event.state = target
    event.save(update_fields=["state"])
    audit.append(event.id, actor.id, "event.state", event.id, {"state": before}, {"state": target})
    return event


def _scored(event_id: str) -> bool:
    return ScoreRev.objects.filter(submission__event_id=event_id).exists()


@transaction.atomic
def set_criteria(event_id: str, actor: Person, body: dict) -> list[dict]:
    """The rubric: criteria and weights for the event, and optional per-track weights.

    Keys are fixed once any score exists (a review must score every criterion). Weights and
    labels can change until publish; each change is audited and the next results fit uses it.
    """
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    refuse_if_published(event)
    before = {"criteria": criteria_rows(event_id)}
    current = list(Criterion.objects.filter(event_id=event_id, track__isnull=True).order_by("position", "key"))
    raw = body.get("criteria")
    if raw in (None, ""):
        # The HTML form posts weight_<key> and label_<key> for the existing criteria.
        raw = [
            {
                "key": row.key,
                "label": body.get(f"label_{row.key}") or row.label or row.key,
                "weight": body.get(f"weight_{row.key}", row.weight),
            }
            for row in current
        ]
    criteria = parse_criteria(raw)
    keys = [row["key"] for row in criteria]
    if _scored(event_id) and sorted(keys) != sorted(row.key for row in current):
        raise Conflict("Scores exist, so the criteria are fixed. Weights and labels can still change.")
    tracks = {row.id for row in event.tracks.all()}
    overrides = body.get("tracks")
    if overrides in (None, ""):
        overrides = {}
        for track in tracks:
            for key in keys:
                value = body.get(f"weight_{track}_{key}")
                if value not in (None, ""):
                    overrides.setdefault(track, {})[key] = value
    if not isinstance(overrides, dict):
        raise Unprocessable({"tracks": "Expected {track_id: {criterion: weight}}."})
    parsed_overrides = {}
    for track, weights in overrides.items():
        if track not in tracks:
            raise Unprocessable({"tracks": f"{track} is not a track of this event."})
        if not isinstance(weights, dict):
            raise Unprocessable({"tracks": "Expected {criterion: weight} for each track."})
        for key, value in weights.items():
            if key not in keys:
                raise Unprocessable({"tracks": f"{key} is not a criterion of this rubric."})
            if value in (None, ""):
                continue
            parsed_overrides.setdefault(track, {})[key] = _weight(value, f"weight:{track}:{key}")
    Criterion.objects.filter(event_id=event_id).delete()
    for position, row in enumerate(criteria):
        Criterion.objects.create(
            event=event, track=None, key=row["key"], label=row["label"], weight=row["weight"], position=position
        )
    for track, weights in parsed_overrides.items():
        for position, row in enumerate(criteria):
            if row["key"] in weights:
                Criterion.objects.create(
                    event=event,
                    track_id=track,
                    key=row["key"],
                    label=row["label"],
                    weight=weights[row["key"]],
                    position=position,
                )
    after = {"criteria": criteria_rows(event_id)}
    audit.append(event_id, actor.id, "rubric.update", event_id, before, after)
    return after["criteria"]


# --- people ----------------------------------------------------------------------------------


def people_payload(event_id: str) -> dict:
    grants = (
        RoleGrant.objects.filter(event_id=event_id)
        .select_related("person")
        .order_by("role", "person__email")
    )
    tracks = {}
    for row in JudgeTrack.objects.filter(event_id=event_id):
        tracks.setdefault(row.person_id, []).append(row.track_id)
    load = {}
    for judge_id, finalized in Assignment.objects.filter(submission__event_id=event_id).values_list(
        "judge_id", "finalized_at"
    ):
        entry = load.setdefault(judge_id, [0, 0])
        entry[0] += 1
        if finalized is not None:
            entry[1] += 1
    items = []
    for grant in grants:
        person = grant.person
        assigned, done = load.get(person.id, [0, 0]) if grant.role == "judge" else ("", "")
        items.append(
            {
                "person_id": person.id,
                "name": person.name,
                "email": person.email,
                "role": grant.role,
                "tracks": " ".join(sorted(tracks.get(person.id, []))) if grant.role == "judge" else "",
                "assigned": assigned,
                "finalized": done,
                "open": (assigned - done) if grant.role == "judge" else "",
                "can_sign_in": "true" if person.has_usable_password() else "false",
                "status": "active",
                "invite_expires": "",
            }
        )
    # Offers to existing accounts that have not been accepted yet. They hold no role until then.
    now = timezone.now()
    pending = (
        Invite.objects.filter(kind="role", event_id=event_id, revoked_at__isnull=True, uses=0, expires_at__gt=now)
        .select_related("person")
        .order_by("role", "person__email")
    )
    for invite in pending:
        person = invite.person
        items.append(
            {
                "person_id": person.id,
                "name": person.name,
                "email": person.email,
                "role": invite.role,
                "tracks": " ".join(invite.tracks) if invite.role == "judge" else "",
                "assigned": "",
                "finalized": "",
                "open": "",
                "can_sign_in": "true" if person.has_usable_password() else "false",
                "status": "invited",
                "invite_expires": stamp(invite.expires_at),
            }
        )
    return {
        "title": "People",
        "event": event_id,
        "resource": "people",
        "columns": [
            "person_id",
            "name",
            "email",
            "role",
            "tracks",
            "assigned",
            "finalized",
            "open",
            "can_sign_in",
            "status",
            "invite_expires",
        ],
        "items": items,
        "count": len(items),
        "tracks": list(Track.objects.filter(event_id=event_id).order_by("id").values("id", "name")),
        "download_csv": f"/e/{event_id}/people.csv",
        "download_json": f"/e/{event_id}/people.json",
        "html_omitted": {},
    }


ROLE_INVITE_DAYS = 14


def _is_fresh_account(person: Person, created: bool) -> bool:
    """An account nobody has used: this invite just created it, or it never had a password and holds
    no role and no team anywhere. Such an account is only reachable through the set-password link
    this organizer hands out, so granting the role at once gives it to nobody else."""
    if created:
        return True
    if person.is_admin or person.has_usable_password():
        return False
    return not (
        RoleGrant.objects.filter(person=person).exists() or TeamMember.objects.filter(person=person).exists()
    )


def _grant(event: Event, person: Person, role: str, tracks: list[str]) -> bool:
    _row, granted = RoleGrant.objects.get_or_create(person=person, event=event, role=role)
    if role == "judge":
        JudgeTrack.objects.filter(person=person, event=event).delete()
        for track in sorted(set(tracks)):
            JudgeTrack.objects.create(person=person, event=event, track_id=track)
    return granted


def _issue_role_invite(event: Event, person: Person, role: str, tracks: list[str], actor: Person) -> tuple[Invite, str]:
    """A one-time link that offers `person` the role. Earlier unused offers of it stop working."""
    now = timezone.now()
    Invite.objects.filter(
        kind="role", event=event, person=person, role=role, revoked_at__isnull=True, uses=0
    ).update(revoked_at=now)
    token = "ra_" + secrets.token_urlsafe(24)
    invite = Invite.objects.create(
        id="inv_" + secrets.token_hex(5),
        kind="role",
        event=event,
        person=person,
        role=role,
        tracks=sorted(set(tracks)) if role == "judge" else [],
        token_sha256=accounts.digest(token),
        expires_at=now + timedelta(days=ROLE_INVITE_DAYS),
        max_uses=1,
        created_by=actor.id,
    )
    return invite, f"{settings.PUBLIC_URL.rstrip('/')}/accept/{token}"


@transaction.atomic
def add_person(event_id: str, actor: Person, body: dict) -> dict:
    """Invite a judge or an organizer by email.

    A new address gets an account with no password and a one-time set-password link; the role comes
    with it, because only that link can ever sign the account in. An address that already has an
    account gets nothing yet: the organizer receives a one-time acceptance link, and the role is
    granted when the owner of that account, signed in, accepts it. Anyone can sign up with any
    address, so an existing account is never proof that its holder is the person being invited.
    """
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    email = accounts.clean_email(body.get("email"))
    name = accounts.clean_name(body.get("name"), required=False)
    role = body.get("role") or "judge"
    if role not in {"judge", "organizer"}:
        raise Unprocessable({"role": "judge or organizer"})
    if role == "judge":
        refuse_if_published(event)
    event_tracks = list(event.tracks.order_by("id").values_list("id", flat=True))
    raw_tracks = body.get("tracks")
    if isinstance(raw_tracks, str):
        raw_tracks = [part for part in raw_tracks.replace(",", " ").split() if part]
    if raw_tracks in (None, []):
        raw_tracks = event_tracks
    if not isinstance(raw_tracks, list) or not all(isinstance(t, str) and t in event_tracks for t in raw_tracks):
        raise Unprocessable({"tracks": "Choose tracks of this event."})
    tracks = sorted(set(raw_tracks)) if role == "judge" else []
    person, created = accounts.ensure_person(email, name)
    if TeamMember.objects.filter(event=event, person=person).exists():
        raise Conflict(f"{email} is on a team in this event, so they cannot be a {role} here.")
    if not person.is_active:
        raise Conflict(f"{email} is deactivated.")
    already = RoleGrant.objects.filter(person=person, event=event, role=role).exists()
    granted = False
    link = ""
    accept_link = ""
    invite_id = ""
    if already:
        # The same role again only changes a judge's tracks.
        _grant(event, person, role, tracks)
        status = "active"
    elif _is_fresh_account(person, created):
        granted = _grant(event, person, role, tracks)
        status = "active"
    else:
        invite, accept_link = _issue_role_invite(event, person, role, tracks, actor)
        invite_id = invite.id
        status = "invited"
    if status == "active" and _may_set_password(person, event_id):
        link = accounts.issue_password_link(person, actor=actor.id, event_id=event_id)
    audit.append(
        event_id,
        actor.id,
        f"people.add_{role}" if status == "active" else f"people.invite_{role}",
        person.id,
        None,
        {
            "email": email,
            "role": role,
            "tracks": tracks,
            "new_account": created,
            "status": status,
            "invite": invite_id,
            "password_link_issued": bool(link),
        },
    )
    return {
        "person_id": person.id,
        "email": person.email,
        "role": role,
        "tracks": tracks,
        "new_account": created,
        "granted": granted,
        # active: the role is held now. invited: it is held once the account's owner accepts accept_link.
        "status": status,
        # Shown once. Only their sha256 is stored.
        "password_link": link,
        "accept_link": accept_link,
    }


def _live_role_invite(token: str, *, lock: bool = False) -> Invite:
    rows = Invite.objects.filter(kind="role", token_sha256=accounts.digest(token)).select_related("person", "event")
    if lock:
        rows = rows.select_for_update(of=("self",))
    invite = rows.first()
    if invite is None or invite.revoked_at is not None or invite.uses >= invite.max_uses:
        raise NotFound("This link is not valid. Ask the organizer for a new one.")
    if invite.expires_at <= timezone.now():
        raise NotFound("This link has expired. Ask the organizer for a new one.")
    return invite


def role_invite_preview(token: str, principal: Person | None) -> dict:
    invite = _live_role_invite(token)
    names = dict(Track.objects.filter(event=invite.event).values_list("id", "name"))
    return {
        "title": f"{invite.role.capitalize()} invitation",
        "event": invite.event_id,
        "resource": "role-invite",
        "event_name": invite.event.name,
        "role": invite.role,
        "tracks": [names.get(track, track) for track in invite.tracks],
        "email": invite.person.email,
        "expires_at": stamp(invite.expires_at),
        "signed_in_as": principal.email if principal is not None else "",
        "is_invitee": bool(principal is not None and principal.id == invite.person_id),
        "columns": [],
        "items": [],
        "count": 0,
        "html_omitted": {},
    }


@transaction.atomic
def accept_role_invite(token: str, principal: Person) -> dict:
    """The invited account, signed in, takes the role it was offered."""
    invite = _live_role_invite(token, lock=True)
    if invite.person_id != principal.id:
        # The link reached the owner of another account. Say which, so they can sign in as it.
        raise PermissionDenied(f"This invitation is for {invite.person.email}. Sign in as that account to accept it.")
    event = Event.objects.select_for_update().get(id=invite.event_id)
    if invite.role == "judge":
        refuse_if_published(event)
    if TeamMember.objects.filter(event=event, person=principal).exists():
        raise Conflict("You are on a team in this event, so you cannot also be a judge or organizer here.")
    if not principal.is_active:
        raise Conflict("This account is deactivated.")
    known = set(event.tracks.values_list("id", flat=True))
    tracks = [track for track in invite.tracks if track in known]
    granted = _grant(event, principal, invite.role, tracks)
    invite.uses += 1
    invite.save(update_fields=["uses"])
    audit.append(
        event.id,
        principal.id,
        f"people.accept_{invite.role}",
        principal.id,
        None,
        {"invite": invite.id, "role": invite.role, "tracks": tracks, "granted": granted},
    )
    return {"event": event.id, "role": invite.role, "tracks": tracks, "granted": True}


def _may_set_password(person: Person, event_id: str) -> bool:
    """An organizer may hand out a set-password link only for an account that has never had a
    password and has no role outside this event. Otherwise an organizer of one event could take
    over a judge's account on another event, or an admin's."""
    if person.is_admin or person.has_usable_password():
        return False
    return not RoleGrant.objects.filter(person=person).exclude(event_id=event_id).exists()


@transaction.atomic
def password_link(event_id: str, actor: Person, person_id: str) -> str:
    """A fresh set-password link for someone on this event who has never set a password.

    A person who already has a password is refused, so an organizer cannot take over an account.
    """
    grant = RoleGrant.objects.filter(event_id=event_id, person_id=person_id).select_related("person").first()
    if grant is None:
        raise NotFound("That person has no role on this event.")
    person = grant.person
    if not _may_set_password(person, event_id):
        raise Conflict(
            "This person already has a password, or an account on another event. "
            "They sign in with it and can change it on their account page."
        )
    link = accounts.issue_password_link(person, actor=actor.id, event_id=event_id)
    audit.append(event_id, actor.id, "people.password_link", person.id, None, {"issued": True})
    return link
