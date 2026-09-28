"""Creates and edits submissions. The deadline is checked before the body is validated."""

from __future__ import annotations

import re
import secrets

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import Submission, TeamMember
from samepage.core.errors import Conflict, Unprocessable
from samepage.domain.deadline import closed_message, is_closed
from samepage.services import audit
from samepage.services.clock import db_now

_TAG = re.compile(r"^[a-z0-9+#.\-]{1,32}$")
_CONTENT = (
    "title",
    "tagline",
    "description",
    "thumbnail",
    "video_url",
    "repo_url",
    "live_url",
    "tech_tags",
    "custom_answers",
    "track_id",
)


def _event_or_403(event_id: str):
    from samepage.apps.portal.models import Event

    event = Event.objects.filter(id=event_id).first()
    if event is None:
        raise PermissionDenied("You cannot do that.")
    return event


def _membership(event_id: str, person):
    return (
        TeamMember.objects.filter(event_id=event_id, person=person)
        .select_related("team")
        .first()
    )


def _closed(event) -> None:
    if is_closed(db_now(), event.submissions_close):
        raise Conflict(closed_message(event.submissions_close))


_TEXT_LIMITS = {
    "title": 200,
    "tagline": 300,
    "description": 20000,
    "video_url": 2000,
    "repo_url": 2000,
    "live_url": 2000,
}


def _text(body: dict, errors: dict, field: str, *aliases: str) -> str:
    """A text field, or an error. A number or a list is refused, never coerced into a 500."""
    value = None
    for key in (field, *aliases):
        if body.get(key) not in (None, ""):
            value = body.get(key)
            break
    if value is None:
        return ""
    if not isinstance(value, str):
        errors[field] = "Expected text."
        return ""
    value = value.strip()
    if len(value) > _TEXT_LIMITS[field]:
        errors[field] = f"At most {_TEXT_LIMITS[field]} characters."
    return value


def _clean(body: dict, *, partial: bool) -> dict:
    errors = {}
    title = _text(body, errors, "title", "name")
    tagline = _text(body, errors, "tagline", "summary")
    description = _text(body, errors, "description")
    video_url = _text(body, errors, "video_url")
    repo_url = _text(body, errors, "repo_url")
    live_url = _text(body, errors, "live_url")
    if not partial and not title and "title" not in errors:
        errors["title"] = "Title is required."
    tags = body.get("tech_tags") or []
    if isinstance(tags, str):
        tags = [part for part in tags.replace(",", " ").split() if part]
    if not isinstance(tags, list) or not all(isinstance(tag, str) and _TAG.match(tag) for tag in tags):
        errors["tech_tags"] = "Tags are lowercase letters, digits and + # . -"
        tags = []
    if "custom_answers" in body and not isinstance(body["custom_answers"], dict):
        errors["custom_answers"] = "Expected an object."
    if errors:
        raise Unprocessable(errors)
    cleaned = {
        "title": title,
        "tagline": tagline,
        "description": description,
        "video_url": video_url,
        "repo_url": repo_url,
        "live_url": live_url,
        "tech_tags": [str(tag) for tag in tags],
    }
    if "custom_answers" in body and isinstance(body["custom_answers"], dict):
        cleaned["custom_answers"] = {str(k): str(v) for k, v in body["custom_answers"].items()}
    return cleaned


def _track(event, body: dict) -> str | None:
    """The track must belong to this event. A track id from another event is refused."""
    track_id = body.get("track") or body.get("track_id")
    if track_id in (None, ""):
        return event.tracks.order_by("id").values_list("id", flat=True).first()
    if not isinstance(track_id, str) or not event.tracks.filter(id=track_id).exists():
        raise Unprocessable({"track": "Choose a track of this event."})
    return track_id


@transaction.atomic
def create(event_id: str, person, body: dict) -> Submission:
    event = _event_or_403(event_id)
    _closed(event)
    cleaned = _clean(body, partial=False)
    membership = _membership(event_id, person)
    if membership is None:
        raise PermissionDenied("You are not on a team for this event.")
    TeamMember.objects.select_for_update().get(pk=membership.pk)
    track_id = _track(event, body)
    submission = Submission(
        id="prj_" + secrets.token_hex(4),
        event=event,
        team=membership.team,
        track_id=track_id,
        position=9000,
        title=cleaned["title"],
        tagline=cleaned["tagline"],
        description=cleaned["description"],
        video_url=cleaned["video_url"],
        repo_url=cleaned["repo_url"],
        live_url=cleaned["live_url"],
        tech_tags=cleaned["tech_tags"],
        custom_answers=cleaned.get("custom_answers") or {},
        state="submitted",
        origin="native",
        submitted_at=db_now(),
    )
    try:
        submission.save()
    except IntegrityError as exc:
        raise Conflict("This team already has an active submission.") from exc
    audit.append(
        event_id,
        person.id,
        "submission.create",
        submission.id,
        None,
        {"title": submission.title, "state": submission.state},
    )
    return submission


def detail(event_id: str, project_id: str, *, principal, roles: set[str]) -> dict:
    submission = (
        Submission.objects.filter(event_id=event_id, id=project_id)
        .select_related("track", "team")
        .first()
    )
    if submission is None:
        raise NotFound("Unknown project.")
    staff = bool(roles & {"organizer", "admin"})
    on_team = principal is not None and TeamMember.objects.filter(
        event_id=event_id, person=principal, team_id=submission.team_id
    ).exists()
    if submission.state == "draft" and not (staff or on_team):
        raise PermissionDenied("You cannot do that.")
    blind = submission.event.blind_judging and "judge" in roles and not staff
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
        "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
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
    return {
        "title": submission.title,
        "event": event_id,
        "resource": "project",
        "item": item,
        "columns": list(item.keys()),
        "items": [item],
        "count": 1,
        "html_omitted": omitted,
        "download_json": f"/e/{event_id}/projects/{submission.id}.json",
    }
