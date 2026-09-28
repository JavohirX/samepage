"""Teams: create one, invite by secret link, join, leave, and organizer removal.

A person is on at most one team per event (unique constraint). Team changes close with
submissions, because the team owns the submission. Joins and leaves are audited.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from samepage.apps.portal.models import Event, Invite, Person, RoleGrant, Submission, Team, TeamMember
from samepage.core.errors import Conflict, Unprocessable
from samepage.domain.deadline import closed_message, is_closed
from samepage.services import audit
from samepage.services.accounts import digest
from samepage.services.clock import db_now

INVITE_DAYS_DEFAULT = 7
INVITE_USES_DEFAULT = 3


def _staff(person: Person | None, event_id: str) -> bool:
    if person is None:
        return False
    if person.is_admin:
        return True
    return RoleGrant.objects.filter(person=person, event_id=event_id, role="organizer").exists()


def _open_for_teams(event: Event) -> None:
    if is_closed(db_now(), event.submissions_close):
        raise Conflict(closed_message(event.submissions_close) + "; teams are fixed now")
    if event.state == "draft":
        raise Conflict("The event is not open yet; teams can form once the organizer opens it.")
    if event.state != "open":
        raise Conflict(f"The event is {event.state}; teams are fixed now.")


def _not_staff_or_judge(event: Event, person: Person) -> None:
    if person.is_admin:
        raise Conflict("Admins run events; they cannot be on a team.")
    roles = set(RoleGrant.objects.filter(person=person, event=event).values_list("role", flat=True))
    if roles & {"judge", "organizer"}:
        raise Conflict("Judges and organizers of this event cannot be on a team in it.")


def _join(event: Event, team: Team, person: Person) -> None:
    if TeamMember.objects.filter(event=event, person=person).exists():
        raise Conflict("You are already on a team in this event. Leave it first.")
    members = TeamMember.objects.select_for_update().filter(team=team).count()
    if members >= event.max_team_size:
        raise Conflict(f"This team is full ({event.max_team_size} people).")
    try:
        with transaction.atomic():
            TeamMember.objects.create(event=event, team=team, person=person)
    except IntegrityError as exc:
        raise Conflict("You are already on a team in this event.") from exc
    RoleGrant.objects.get_or_create(person=person, event=event, role="participant")


def _clean_team_name(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Unprocessable({"name": "A team needs a name."})
    name = value.strip()
    if len(name) > 80:
        raise Unprocessable({"name": "At most 80 characters."})
    return name


@transaction.atomic
def create(event_id: str, person: Person, body: dict) -> Team:
    event = Event.objects.select_for_update().filter(id=event_id).first()
    if event is None:
        raise NotFound("Unknown event.")
    _open_for_teams(event)
    _not_staff_or_judge(event, person)
    name = _clean_team_name(body.get("name"))
    if Team.objects.filter(event=event, name__iexact=name).exists():
        raise Conflict("A team with this name already exists in this event.")
    team = Team.objects.create(id="tm_" + secrets.token_hex(4), event=event, name=name)
    _join(event, team, person)
    audit.append(event_id, person.id, "team.create", team.id, None, {"name": name})
    return team


def _team(event_id: str, team_id: str, *, lock: bool = False) -> Team:
    rows = Team.objects.filter(event_id=event_id, id=team_id).select_related("event")
    if lock:
        rows = rows.select_for_update()
    team = rows.first()
    if team is None:
        raise NotFound("Unknown team.")
    return team


def _member_or_staff(team: Team, person: Person | None) -> bool:
    if person is None:
        return False
    return TeamMember.objects.filter(team=team, person=person).exists() or _staff(person, team.event_id)


def team_payload(event_id: str, team_id: str, person: Person | None) -> dict:
    team = _team(event_id, team_id)
    if not _member_or_staff(team, person):
        raise PermissionDenied("You cannot do that.")
    members = [
        {"person_id": row.person_id, "name": row.person.name, "email": row.person.email}
        for row in TeamMember.objects.filter(team=team).select_related("person").order_by("person__email")
    ]
    submission = (
        Submission.objects.filter(event_id=event_id, team=team, origin="native")
        .exclude(state="withdrawn")
        .first()
    )
    if submission is None:
        submission = Submission.objects.filter(event_id=event_id, team=team).exclude(state="withdrawn").first()
    now = timezone.now()
    invites = [
        {
            "id": row.id,
            "expires_at": row.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uses": row.uses,
            "max_uses": row.max_uses,
            "active": "true" if row.revoked_at is None and row.expires_at > now and row.uses < row.max_uses else "false",
        }
        for row in Invite.objects.filter(team=team, kind="team").order_by("-created_at")
    ]
    closed = is_closed(db_now(), team.event.submissions_close)
    is_member = person is not None and any(row["person_id"] == person.id for row in members)
    return {
        "title": team.name,
        "event": event_id,
        "resource": "team",
        "id": team.id,
        "name": team.name,
        "members": members,
        "max_team_size": team.event.max_team_size,
        "invites": invites,
        "submission": (
            {"id": submission.id, "title": submission.title, "state": submission.state} if submission else None
        ),
        "closed": "true" if closed else "false",
        "is_member": is_member,
        "is_staff": _staff(person, event_id),
        "columns": ["person_id", "name", "email"],
        "items": members,
        "count": len(members),
        "html_omitted": {},
        "download_json": f"/e/{event_id}/teams/{team.id}.json",
    }


def teams_payload(event_id: str) -> dict:
    items = []
    for team in Team.objects.filter(event_id=event_id).order_by("id").prefetch_related("members__person"):
        members = sorted(row.person.email for row in team.members.all())
        items.append({"id": team.id, "name": team.name, "size": len(members), "members": " ".join(members)})
    return {
        "title": "Teams",
        "event": event_id,
        "resource": "teams",
        "columns": ["id", "name", "size", "members"],
        "items": items,
        "count": len(items),
        "download_csv": f"/e/{event_id}/teams.csv",
        "download_json": f"/e/{event_id}/teams.json",
        "html_omitted": {},
    }


def _whole(value, default: int, low: int, high: int, field: str) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise Unprocessable({field: f"A whole number from {low} to {high}."})
    try:
        number = int(str(value).strip())
    except ValueError:
        raise Unprocessable({field: f"A whole number from {low} to {high}."}) from None
    if not low <= number <= high:
        raise Unprocessable({field: f"A whole number from {low} to {high}."})
    return number


@transaction.atomic
def create_invite(event_id: str, team_id: str, person: Person, body: dict) -> dict:
    team = _team(event_id, team_id, lock=True)
    if not TeamMember.objects.filter(team=team, person=person).exists():
        raise PermissionDenied("Only members of this team can invite to it.")
    _open_for_teams(team.event)
    days = _whole(body.get("days"), INVITE_DAYS_DEFAULT, 1, 30, "days")
    uses = _whole(body.get("max_uses"), INVITE_USES_DEFAULT, 1, 20, "max_uses")
    token = "tj_" + secrets.token_urlsafe(24)
    invite = Invite.objects.create(
        id="inv_" + secrets.token_hex(5),
        kind="team",
        event_id=event_id,
        team=team,
        token_sha256=digest(token),
        expires_at=timezone.now() + timedelta(days=days),
        max_uses=uses,
        created_by=person.id,
    )
    audit.append(event_id, person.id, "invite.create", invite.id, None, {"team": team.id, "days": days, "max_uses": uses})
    return {
        "id": invite.id,
        "team": team.id,
        "expires_at": invite.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_uses": uses,
        # Shown once. Only its sha256 is stored.
        "url": f"{settings.PUBLIC_URL.rstrip('/')}/join/{token}",
        "path": f"/join/{token}",
    }


@transaction.atomic
def revoke_invite(event_id: str, team_id: str, invite_id: str, person: Person) -> Invite:
    team = _team(event_id, team_id)
    if not _member_or_staff(team, person):
        raise PermissionDenied("You cannot do that.")
    invite = Invite.objects.select_for_update().filter(id=invite_id, team=team, kind="team").first()
    if invite is None:
        raise NotFound("Unknown invite.")
    if invite.revoked_at is None:
        invite.revoked_at = timezone.now()
        invite.save(update_fields=["revoked_at"])
        audit.append(event_id, person.id, "invite.revoke", invite.id, None, {"team": team.id})
    return invite


def _live_team_invite(token: str, *, lock: bool = False) -> Invite:
    rows = Invite.objects.filter(kind="team", token_sha256=digest(token)).select_related("team", "team__event")
    if lock:
        # Lock the invite row only: the joined team/person side is nullable, so it cannot be locked.
        rows = rows.select_for_update(of=("self",))
    invite = rows.first()
    if invite is None or invite.revoked_at is not None:
        raise NotFound("This invite link is not valid.")
    if invite.expires_at <= timezone.now():
        raise NotFound("This invite link has expired. Ask the team for a new one.")
    if invite.uses >= invite.max_uses:
        raise NotFound("This invite link has been used up. Ask the team for a new one.")
    return invite


def invite_preview(token: str) -> dict:
    invite = _live_team_invite(token)
    team = invite.team
    return {
        "title": f"Join {team.name}",
        "event": team.event_id,
        "resource": "invite",
        "team_id": team.id,
        "team_name": team.name,
        "event_name": team.event.name,
        "members": TeamMember.objects.filter(team=team).count(),
        "max_team_size": team.event.max_team_size,
        "expires_at": invite.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "columns": ["team_id", "team_name"],
        "items": [{"team_id": team.id, "team_name": team.name}],
        "count": 1,
        "html_omitted": {"members": "member names are shown after you join"},
    }


@transaction.atomic
def accept(token: str, person: Person) -> Team:
    invite = _live_team_invite(token, lock=True)
    team = invite.team
    event = Event.objects.select_for_update().get(id=team.event_id)
    _open_for_teams(event)
    _not_staff_or_judge(event, person)
    _join(event, team, person)
    invite.uses += 1
    invite.save(update_fields=["uses"])
    audit.append(event.id, person.id, "team.join", team.id, None, {"invite": invite.id, "person": person.id})
    return team


def _drop(event: Event, team: Team, person: Person, *, actor: Person, action: str) -> None:
    membership = TeamMember.objects.select_for_update().filter(team=team, person=person).first()
    if membership is None:
        raise NotFound("Not a member of this team.")
    remaining = TeamMember.objects.filter(team=team).exclude(person=person).count()
    active = Submission.objects.filter(team=team).exclude(state="withdrawn").exists()
    if remaining == 0 and active:
        raise Conflict("The last member cannot leave while the team has a submission. Withdraw it first.")
    membership.delete()
    RoleGrant.objects.filter(person=person, event=event, role="participant").delete()
    audit.append(event.id, actor.id, action, team.id, {"person": person.id}, None)
    if remaining == 0 and not Submission.objects.filter(team=team).exists():
        Invite.objects.filter(team=team).delete()
        team.delete()


@transaction.atomic
def leave(event_id: str, team_id: str, person: Person) -> None:
    team = _team(event_id, team_id, lock=True)
    event = Event.objects.select_for_update().get(id=event_id)
    _open_for_teams(event)
    _drop(event, team, person, actor=person, action="team.leave")


@transaction.atomic
def remove_member(event_id: str, team_id: str, person_id: str, actor: Person) -> None:
    team = _team(event_id, team_id, lock=True)
    if not _staff(actor, event_id):
        raise PermissionDenied("Only organizers remove team members.")
    event = Event.objects.select_for_update().get(id=event_id)
    _open_for_teams(event)
    member = Person.objects.filter(id=person_id).first()
    if member is None:
        raise NotFound("Unknown person.")
    _drop(event, team, member, actor=actor, action="team.remove")


def my_team_id(event_id: str, person: Person | None) -> str | None:
    if person is None:
        return None
    return TeamMember.objects.filter(event_id=event_id, person=person).values_list("team_id", flat=True).first()
