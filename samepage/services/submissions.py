"""Submissions: a team's draft, its edits until the deadline, submit, withdraw, and images.

The deadline is checked before the body is validated, by the service and again by database
triggers (submission and submission_media). A draft is visible to its team and to organizers.
"""

from __future__ import annotations

import hashlib
import re
import secrets

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import Event, RoleGrant, Submission, SubmissionMedia, TeamMember
from samepage.core.errors import Conflict, Unprocessable
from samepage.domain.deadline import closed_message, is_closed
from samepage.services import audit
from samepage.services.clock import db_now

_TAG = re.compile(r"^[a-z0-9+#.\-]{1,32}$")
MAX_TAGS = 12
MAX_GALLERY = 6
MAX_IMAGE_BYTES = 2 * 1024 * 1024

_TEXT_LIMITS = {
    "title": 200,
    "tagline": 300,
    "description": 20000,
    "video_url": 2000,
    "repo_url": 2000,
    "live_url": 2000,
}
_URL_FIELDS = ("video_url", "repo_url", "live_url")


def _event_or_403(event_id: str) -> Event:
    event = Event.objects.filter(id=event_id).first()
    if event is None:
        raise PermissionDenied("You cannot do that.")
    return event


def _membership(event_id: str, person):
    return TeamMember.objects.filter(event_id=event_id, person=person).select_related("team").first()


def _closed(event) -> None:
    if is_closed(db_now(), event.submissions_close):
        raise Conflict(closed_message(event.submissions_close))


def _accepting(event) -> None:
    """Deadline first (the checker's closed event gets its 409 before anything else), then state and start."""
    _closed(event)
    if event.state != "open":
        raise Conflict(f"The event is {event.state}, not open for submissions.")
    if event.starts_at is not None and db_now() < event.starts_at:
        raise Conflict("Submissions open at " + event.starts_at.strftime("%Y-%m-%dT%H:%M:%SZ") + ".")


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


def _text(body: dict, errors: dict, field: str, *aliases: str) -> str | None:
    """A text field, None when absent, or an error. A number or a list is refused, never coerced into a 500."""
    present = False
    value = None
    for key in (field, *aliases):
        if key in body:
            present = True
            if body.get(key) not in (None, ""):
                value = body.get(key)
                break
    if not present:
        return None
    if value is None:
        return ""
    if not isinstance(value, str):
        errors[field] = "Expected text."
        return ""
    value = value.strip()
    if len(value) > _TEXT_LIMITS[field]:
        errors[field] = f"At most {_TEXT_LIMITS[field]} characters."
    if field in _URL_FIELDS and value and not re.match(r"^https?://[^\s]+$", value):
        errors[field] = "A link starting with http:// or https://."
    return value


def _tags(body: dict, errors: dict) -> list[str] | None:
    if "tech_tags" not in body:
        return None
    tags = body.get("tech_tags") or []
    if isinstance(tags, str):
        tags = [part for part in tags.replace(",", " ").split() if part]
    if not isinstance(tags, list) or not all(isinstance(tag, str) and _TAG.match(tag) for tag in tags):
        errors["tech_tags"] = "Tags are lowercase letters, digits and + # . -"
        return []
    unique = list(dict.fromkeys(tags))
    if len(unique) > MAX_TAGS:
        errors["tech_tags"] = f"At most {MAX_TAGS} tags."
    return unique


def _answers(event: Event, body: dict, errors: dict) -> dict | None:
    """Custom answers: a JSON object, or form fields q_<key>. Only the event's questions are kept."""
    questions = event.custom_questions or []
    raw = body.get("custom_answers")
    if raw is None:
        found = {q["key"]: body.get(f"q_{q['key']}") for q in questions if f"q_{q['key']}" in body}
        if not found:
            return None
        raw = found
    if not isinstance(raw, dict):
        errors["custom_answers"] = "Expected an object."
        return None
    answers = {}
    for question in questions:
        if question["key"] not in raw:
            continue
        value = raw.get(question["key"])
        if value in (None, ""):
            # Present but empty clears the answer (the edit form posts every question).
            answers[question["key"]] = ""
            continue
        if not isinstance(value, str) or len(value) > 2000:
            errors[f"q_{question['key']}"] = "Expected text of at most 2000 characters."
            continue
        value = value.strip()
        if question["kind"] == "choice" and value not in question["choices"]:
            errors[f"q_{question['key']}"] = "Choose one of: " + ", ".join(question["choices"])
            continue
        answers[question["key"]] = value
    unknown = set(raw) - {q["key"] for q in questions}
    if unknown:
        errors["custom_answers"] = "Unknown question(s): " + ", ".join(sorted(unknown))
    return answers


def _track(event, body: dict, current: str | None = None) -> str | None:
    """The track must belong to this event. A track id from another event is refused."""
    if "track" not in body and "track_id" not in body:
        return current or event.tracks.order_by("id").values_list("id", flat=True).first()
    track_id = body.get("track") or body.get("track_id")
    if track_id in (None, ""):
        return current or event.tracks.order_by("id").values_list("id", flat=True).first()
    if not isinstance(track_id, str) or not event.tracks.filter(id=track_id).exists():
        raise Unprocessable({"track": "Choose a track of this event."})
    return track_id


def _clean(event: Event, body: dict, *, creating: bool) -> dict:
    errors: dict = {}
    cleaned = {
        "title": _text(body, errors, "title", "name"),
        "tagline": _text(body, errors, "tagline", "summary"),
        "description": _text(body, errors, "description"),
        "video_url": _text(body, errors, "video_url"),
        "repo_url": _text(body, errors, "repo_url"),
        "live_url": _text(body, errors, "live_url"),
        "tech_tags": _tags(body, errors),
        "custom_answers": _answers(event, body, errors),
    }
    if (creating or cleaned["title"] is not None) and not cleaned["title"] and "title" not in errors:
        errors["title"] = "Title is required."
    if errors:
        raise Unprocessable(errors)
    return {key: value for key, value in cleaned.items() if value is not None}


def _missing_for_submit(event: Event, submission: Submission) -> dict:
    missing = {}
    if not submission.title:
        missing["title"] = "Title is required."
    for question in event.custom_questions or []:
        if question.get("required") and not (submission.custom_answers or {}).get(question["key"]):
            missing[f"q_{question['key']}"] = f"{question['label']} is required to submit."
    return missing


@transaction.atomic
def create(event_id: str, person, body: dict) -> Submission:
    event = _event_or_403(event_id)
    _accepting(event)
    membership = _membership(event_id, person)
    if membership is None:
        raise PermissionDenied("You are not on a team for this event. Create or join one first.")
    cleaned = _clean(event, body, creating=True)
    TeamMember.objects.select_for_update().get(pk=membership.pk)
    track_id = _track(event, body)
    submit = _flag(body.get("submit"))
    submission = Submission(
        id="prj_" + secrets.token_hex(4),
        event=event,
        team=membership.team,
        track_id=track_id,
        position=9000,
        title=cleaned.get("title", ""),
        tagline=cleaned.get("tagline", ""),
        description=cleaned.get("description", ""),
        video_url=cleaned.get("video_url", ""),
        repo_url=cleaned.get("repo_url", ""),
        live_url=cleaned.get("live_url", ""),
        tech_tags=cleaned.get("tech_tags", []),
        custom_answers={key: value for key, value in (cleaned.get("custom_answers") or {}).items() if value},
        state="draft",
        origin="native",
    )
    if submit:
        missing = _missing_for_submit(event, submission)
        if missing:
            raise Unprocessable(missing)
        submission.state = "submitted"
        submission.submitted_at = db_now()
    try:
        with transaction.atomic():
            submission.save()
    except IntegrityError as exc:
        raise Conflict("This team already has an active submission. Edit that one.") from exc
    audit.append(
        event_id,
        person.id,
        "submission.create",
        submission.id,
        None,
        {"title": submission.title, "state": submission.state},
    )
    return submission


def _own(event_id: str, project_id: str, person, *, lock: bool = True) -> tuple[Event, Submission]:
    event = _event_or_403(event_id)
    rows = Submission.objects.filter(event_id=event_id, id=project_id)
    if lock:
        rows = rows.select_for_update()
    submission = rows.first()
    if submission is None:
        raise NotFound("Unknown project.")
    if not TeamMember.objects.filter(event_id=event_id, team_id=submission.team_id, person=person).exists():
        raise PermissionDenied("Only the team can change its submission.")
    return event, submission


def _content(submission: Submission) -> dict:
    return {
        "title": submission.title,
        "tagline": submission.tagline,
        "track": submission.track_id,
        "tech_tags": list(submission.tech_tags or []),
        "repo_url": submission.repo_url,
        "live_url": submission.live_url,
        "video_url": submission.video_url,
        "state": submission.state,
    }


@transaction.atomic
def update(event_id: str, project_id: str, person, body: dict) -> Submission:
    event, submission = _own(event_id, project_id, person)
    _accepting(event)
    if submission.state == "withdrawn":
        raise Conflict("This submission was withdrawn.")
    cleaned = _clean(event, body, creating=False)
    before = _content(submission)
    answers = cleaned.pop("custom_answers", None)
    for field, value in cleaned.items():
        setattr(submission, field, value)
    if answers is not None:
        # A partial update keeps the answers it does not mention.
        merged = {**(submission.custom_answers or {}), **answers}
        submission.custom_answers = {key: value for key, value in merged.items() if value}
    submission.track_id = _track(event, body, submission.track_id)
    if submission.state == "submitted" and _missing_for_submit(event, submission):
        raise Unprocessable(_missing_for_submit(event, submission))
    submission.version += 1
    submission.save()
    audit.append(event_id, person.id, "submission.update", submission.id, before, _content(submission))
    return submission


@transaction.atomic
def submit(event_id: str, project_id: str, person) -> Submission:
    event, submission = _own(event_id, project_id, person)
    _accepting(event)
    if submission.state == "submitted":
        return submission
    if submission.state != "draft":
        raise Conflict(f"A {submission.state} submission cannot be submitted.")
    missing = _missing_for_submit(event, submission)
    if missing:
        raise Unprocessable(missing)
    submission.state = "submitted"
    submission.submitted_at = db_now()
    submission.save(update_fields=["state", "submitted_at"])
    audit.append(event_id, person.id, "submission.submit", submission.id, {"state": "draft"}, {"state": "submitted"})
    return submission


@transaction.atomic
def withdraw(event_id: str, project_id: str, person, body: dict) -> Submission:
    event = _event_or_403(event_id)
    submission = Submission.objects.select_for_update().filter(event_id=event_id, id=project_id).first()
    if submission is None:
        raise NotFound("Unknown project.")
    staff = person.is_admin or RoleGrant.objects.filter(person=person, event=event, role="organizer").exists()
    member = TeamMember.objects.filter(event=event, team_id=submission.team_id, person=person).exists()
    if not (staff or member):
        raise PermissionDenied("Only the team or an organizer can withdraw this submission.")
    if not staff:
        # A team may withdraw until the deadline. After it, only an organizer can (e.g. a rules breach).
        _closed(event)
    from samepage.services.guards import refuse_if_published

    refuse_if_published(event)
    if submission.state == "withdrawn":
        return submission
    reason = body.get("reason") or ""
    if not isinstance(reason, str) or len(reason) > 500:
        raise Unprocessable({"reason": "Text of at most 500 characters."})
    before = submission.state
    submission.state = "withdrawn"
    submission.withdrawn_reason = reason.strip() or ("withdrawn by organizer" if staff and not member else "withdrawn by team")
    submission.save(update_fields=["state", "withdrawn_reason"])
    audit.append(event_id, person.id, "submission.withdraw", submission.id, {"state": before}, {"state": "withdrawn", "reason": submission.withdrawn_reason})
    return submission


# --- images ----------------------------------------------------------------------------------


def sniff_image(data: bytes) -> str | None:
    """The content type from the file's first bytes. SVG and everything else are refused."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def media_url(event_id: str, project_id: str, media_id: int) -> str:
    return f"/e/{event_id}/projects/{project_id}/media/{media_id}"


@transaction.atomic
def add_media(event_id: str, project_id: str, person, upload, kind) -> SubmissionMedia:
    event, submission = _own(event_id, project_id, person)
    _accepting(event)
    if kind not in {"thumbnail", "gallery"}:
        raise Unprocessable({"kind": "thumbnail or gallery"})
    if upload is None:
        raise Unprocessable({"file": "Attach an image file (multipart field 'file')."})
    if upload.size > MAX_IMAGE_BYTES:
        raise Unprocessable({"file": "Images are at most 2 MB."})
    data = upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise Unprocessable({"file": "Images are at most 2 MB."})
    content_type = sniff_image(data)
    if content_type is None:
        raise Unprocessable({"file": "PNG, JPEG, GIF or WebP only."})
    if kind == "thumbnail":
        SubmissionMedia.objects.filter(submission=submission, kind="thumbnail").delete()
        position = 0
    else:
        used = set(SubmissionMedia.objects.filter(submission=submission, kind="gallery").values_list("position", flat=True))
        free = [slot for slot in range(1, MAX_GALLERY + 1) if slot not in used]
        if not free:
            raise Conflict(f"The gallery holds {MAX_GALLERY} images. Remove one first.")
        position = free[0]
    media = SubmissionMedia.objects.create(
        submission=submission,
        kind=kind,
        position=position,
        sha256=hashlib.sha256(data).hexdigest(),
        content_type=content_type,
        data=data,
        size=len(data),
    )
    if kind == "thumbnail":
        submission.thumbnail = media_url(event_id, project_id, media.id)
        submission.save(update_fields=["thumbnail"])
    audit.append(event_id, person.id, "media.add", submission.id, None, {"kind": kind, "sha256": media.sha256, "bytes": media.size})
    return media


@transaction.atomic
def remove_media(event_id: str, project_id: str, media_id: int, person) -> None:
    event, submission = _own(event_id, project_id, person)
    _accepting(event)
    media = SubmissionMedia.objects.filter(submission=submission, id=media_id).first()
    if media is None:
        raise NotFound("Unknown image.")
    if media.kind == "thumbnail":
        submission.thumbnail = ""
        submission.save(update_fields=["thumbnail"])
    audit.append(event_id, person.id, "media.remove", submission.id, {"kind": media.kind, "sha256": media.sha256}, None)
    media.delete()


def _visible(submission: Submission, principal, roles: set[str]) -> None:
    staff = bool(roles & {"organizer", "admin"})
    on_team = principal is not None and TeamMember.objects.filter(
        event_id=submission.event_id, person=principal, team_id=submission.team_id
    ).exists()
    if submission.state == "draft" and not (staff or on_team):
        raise PermissionDenied("You cannot do that.")


def media_file(event_id: str, project_id: str, media_id: int, *, principal, roles: set[str]) -> SubmissionMedia:
    submission = Submission.objects.filter(event_id=event_id, id=project_id).first()
    if submission is None:
        raise NotFound("Unknown project.")
    _visible(submission, principal, roles)
    media = SubmissionMedia.objects.filter(submission=submission, id=media_id).first()
    if media is None:
        raise NotFound("Unknown image.")
    return media


# --- reads -----------------------------------------------------------------------------------


def detail(event_id: str, project_id: str, *, principal, roles: set[str]) -> dict:
    submission = (
        Submission.objects.filter(event_id=event_id, id=project_id)
        .select_related("track", "team", "event")
        .first()
    )
    if submission is None:
        raise NotFound("Unknown project.")
    staff = bool(roles & {"organizer", "admin"})
    on_team = principal is not None and TeamMember.objects.filter(
        event_id=event_id, person=principal, team_id=submission.team_id
    ).exists()
    _visible(submission, principal, roles)
    event = submission.event
    blind = event.blind_judging and "judge" in roles and not staff
    questions = event.custom_questions or []
    answers = submission.custom_answers or {}
    item = {
        "id": submission.id,
        "title": submission.title,
        "tagline": submission.tagline,
        "description": submission.description,
        "track": submission.track_id,
        "track_name": submission.track.name,
        "state": submission.state,
        "repo_url": submission.repo_url,
        "live_url": submission.live_url,
        "video_url": submission.video_url,
        "tech_tags": " ".join(submission.tech_tags or []),
        "thumbnail": submission.thumbnail,
        "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
        "version": submission.version,
        "badge": "",
    }
    if submission.state == "withdrawn" and submission.withdrawn_reason.startswith("duplicate_of:"):
        item["badge"] = "withdrawn: duplicate of " + submission.withdrawn_reason.split(":", 1)[1]
    omitted = {}
    if blind:
        omitted["team_name"] = "blind judging is on"
        omitted["team_id"] = "blind judging is on"
    else:
        item["team_name"] = submission.team.name
        item["team_id"] = submission.team_id
    if not (staff or on_team):
        omitted["member_emails"] = "team emails are private"
    media = [
        {"id": row.id, "kind": row.kind, "url": media_url(event_id, submission.id, row.id), "content_type": row.content_type, "bytes": row.size}
        for row in SubmissionMedia.objects.filter(submission=submission).order_by("kind", "position").defer("data")
    ]
    closed = is_closed(db_now(), event.submissions_close)
    from samepage.services import comments

    public_comments = comments.list_public_comments(submission)
    return {
        "title": submission.title,
        "event": event_id,
        "resource": "project",
        "item": item,
        "answers": [
            {"key": q["key"], "label": q["label"], "answer": answers.get(q["key"], "")} for q in questions
        ],
        "media": media,
        "comments": public_comments,
        "can_edit": bool(on_team and not closed and event.state == "open" and submission.state != "withdrawn"),
        "can_withdraw": bool((on_team and not closed) or staff) and submission.state != "withdrawn" and event.state not in {"published", "archived"},
        "columns": list(item.keys()),
        "items": [item],
        "count": 1,
        "html_omitted": omitted,
        "download_json": f"/e/{event_id}/projects/{submission.id}.json",
    }


def form_payload(event_id: str, principal, project_id: str | None = None) -> dict:
    """What the new and edit forms need: the event's tracks and questions, and the current values."""
    event = _event_or_403(event_id)
    values = {
        "title": "",
        "tagline": "",
        "description": "",
        "video_url": "",
        "repo_url": "",
        "live_url": "",
        "tech_tags": "",
        "track": event.tracks.order_by("id").values_list("id", flat=True).first() or "",
        "answers": {},
        "state": "",
    }
    media = []
    if project_id:
        event, submission = _own(event_id, project_id, principal, lock=False)
        values.update(
            {
                "title": submission.title,
                "tagline": submission.tagline,
                "description": submission.description,
                "video_url": submission.video_url,
                "repo_url": submission.repo_url,
                "live_url": submission.live_url,
                "tech_tags": " ".join(submission.tech_tags or []),
                "track": submission.track_id,
                "answers": submission.custom_answers or {},
                "state": submission.state,
            }
        )
        media = [
            {"id": row.id, "kind": row.kind, "url": media_url(event_id, submission.id, row.id)}
            for row in SubmissionMedia.objects.filter(submission=submission).order_by("kind", "position").defer("data")
        ]
    elif _membership(event_id, principal) is None:
        raise PermissionDenied("You are not on a team for this event. Create or join one first.")
    questions = [
        {**q, "value": values["answers"].get(q["key"], "")} for q in (event.custom_questions or [])
    ]
    closed = is_closed(db_now(), event.submissions_close)
    return {
        "title": "Edit submission" if project_id else "New submission",
        "event": event_id,
        "resource": "submission-form",
        "project_id": project_id or "",
        "values": values,
        "tracks": list(event.tracks.order_by("id").values("id", "name")),
        "questions": questions,
        "media": media,
        "closes": event.submissions_close.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "open": bool(not closed and event.state == "open"),
        "columns": [],
        "items": [],
        "count": 0,
        "html_omitted": {},
    }
