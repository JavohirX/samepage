"""HTTP resources. Each one is a SamepageView. Writes call services and then pick HTML or JSON."""

from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework.exceptions import MethodNotAllowed, NotFound

from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    Ballot,
    Batch,
    Event,
    MailOutbox,
    Person,
    ProjectComment,
    RoleGrant,
    Submission,
    TeamMember,
    VotingConfig,
)
from samepage.core.csrf import enforce_csrf
from samepage.core.errors import Unprocessable, problem_response
from samepage.core.headers import annotate
from samepage.core.policy import hidden_fields
from samepage.core.throttles import BallotThrottle, CommentThrottle, LoginThrottle, MagicLinkThrottle
from samepage.core.renderers import negotiate, render_payload
from samepage.core.views import NUL_MESSAGE, SamepageView, nul_field
from samepage.domain.deadline import is_closed
from samepage.domain.tokens import DEMO_PASSWORD, PRINCIPALS
from samepage.domain.transitions import EVENT as EVENT_MACHINE
from samepage.services import (
    access,
    accounts,
    comments,
    duplicates,
    events,
    judging,
    ledger,
    results,
    submissions,
    teams,
    voting,
)
from samepage.services.audit import verify
from samepage.services.clock import db_now


logger = logging.getLogger("samepage.errors")


class Redirect303(HttpResponseRedirect):
    status_code = 303


def _wants_html(request, fmt) -> bool:
    if fmt == "html":
        return True
    if fmt in {"json", "csv"}:
        return False
    content_type = request.META.get("CONTENT_TYPE", "")
    if content_type.startswith("application/x-www-form-urlencoded") or content_type.startswith("multipart/"):
        return True
    if request.POST:
        return True
    return False


LIST_FIELDS = ("tracks",)


def _body(request) -> dict:
    """The request body as one flat object. A form post keeps the last value of each field,
    except the multi-select fields in LIST_FIELDS, which keep every value.

    Text with a NUL character is refused here with 422, for every write that reads a body
    (sign-in and sign-up included): Postgres text cannot hold it."""
    data = request.data
    field = nul_field(data)
    if field:
        raise Unprocessable({field: NUL_MESSAGE})
    if hasattr(data, "dict"):
        flat = data.dict()
        for field in LIST_FIELDS:
            if field in data and len(data.getlist(field)) > 1:
                flat[field] = data.getlist(field)
        flat.pop("csrfmiddlewaretoken", None)
        return flat
    if isinstance(data, dict):
        return data
    raise Unprocessable("Expected an object.")


def _done(request, fmt, *, html_to: str, payload: dict, status: int, location: str):
    """A write's answer: 303 to a page for a browser form, JSON with a Location for an API client."""
    if _wants_html(request, fmt):
        return Redirect303(html_to)
    return _json(request, payload, status, location, fmt)


def _next_url(request, value, default: str = "/") -> str:
    nxt = str(value or default)
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return default
    return nxt


def _json(request, payload, status, location, fmt):
    response = JsonResponse(payload, status=status)
    response["Location"] = location
    return annotate(response, request, fmt=fmt, public_cache=False)


# Health and readiness run outside ATOMIC_REQUESTS. Opening the request transaction is itself what
# fails when Postgres is down, which would make liveness depend on the database and turn the
# readiness 503 below into a 500 raised before the view runs.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class HealthView(SamepageView):
    def get(self, request, fmt=None):
        return annotate(JsonResponse({"ok": True}), request, fmt=fmt, public_cache=False)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ReadyView(SamepageView):
    def get(self, request, fmt=None):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError as exc:
            reason = (str(exc).strip().splitlines() or [""])[0]
            logger.warning(
                "not ready correlation_id=%s %s: %s", getattr(request, "correlation_id", ""), type(exc).__name__, reason
            )
            # Readiness is a JSON endpoint in every suffix, so the refusal is problem+json too.
            return problem_response(request, 503, "The database is not reachable.", fmt="json")
        return annotate(JsonResponse({"ok": True}), request, fmt=fmt, public_cache=False)


class HomeView(SamepageView):
    action = "about.read"
    write_action = "event.create"

    def get(self, request, fmt=None):
        principal = request.principal
        mine: dict[str, set[str]] = {}
        teams_of: dict[str, str] = {}
        if principal is not None:
            for event_id, role in RoleGrant.objects.filter(person=principal).values_list("event_id", "role"):
                mine.setdefault(event_id, set()).add(role)
            teams_of = dict(TeamMember.objects.filter(person=principal).values_list("event_id", "team_id"))
        is_admin = bool(principal is not None and principal.is_admin)
        events = []
        for row in Event.objects.order_by("id"):
            roles = set(mine.get(row.id, set()))
            if is_admin:
                roles.add("admin")
            if row.state == "draft" and not roles & {"organizer", "admin"}:
                # A draft event is its organizers' work in progress.
                continue
            events.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "state": row.state,
                    "submissions_close": events_stamp(row.submissions_close),
                    "your_roles": " ".join(sorted(roles)),
                    "your_team": teams_of.get(row.id, ""),
                }
            )
        payload = {
            "title": "Samepage",
            "event": None,
            "pitch": "Every number on every page opens as the rows behind it.",
            "columns": ["id", "name", "state", "submissions_close", "your_roles", "your_team"],
            "items": events,
            "count": len(events),
            "can_create_event": is_admin,
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="home.html", public_cache=not request.principal)

    def post(self, request, fmt=None):
        """POST /e: create an event (global admins). The home page itself takes no POST."""
        if not request.path.startswith("/e"):
            raise MethodNotAllowed("POST")
        event = events.create(request.principal, _body(request))
        location = f"/e/{event.id}"
        return _done(
            request,
            fmt,
            html_to=f"/e/{event.id}/settings",
            payload={"id": event.id, "url": location + ".json", "state": event.state},
            status=201,
            location=location + ".json",
        )


def events_stamp(value):
    return events.stamp(value)


class NewEventView(SamepageView):
    action = "event.create"
    formats = ("html",)

    def get(self, request, fmt=None):
        payload = {
            "title": "New event",
            "event": None,
            "resource": "event-form",
            "columns": [],
            "items": [],
            "count": 0,
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="event_new.html")


class LoginView(SamepageView):
    throttle_classes = [LoginThrottle]
    throttle_scope = "login"

    def get(self, request, fmt=None):
        if request.principal is not None:
            return Redirect303("/")
        response = render(request, "login.html", {"page_title": "Sign in", "error": ""}, status=401)
        return annotate(response, request, fmt=fmt, public_cache=False)

    def post(self, request, fmt=None):
        # Signing in writes a session cookie, so a cross-site form must not be able to do it.
        enforce_csrf(request)
        body = _body(request)
        email = str(body.get("email") or "").strip()
        password = str(body.get("password") or "")
        user = None
        # The demo password is published in this repository. Outside demo mode it never signs anyone in.
        if settings.DEMO_MODE or password != DEMO_PASSWORD:
            user = authenticate(request, email=email, password=password)
        if user is None:
            response = render(
                request,
                "login.html",
                {"page_title": "Sign in", "error": "Those credentials were refused.", "email": email},
                status=401,
            )
            return annotate(response, request, fmt=fmt, public_cache=False)
        login(request, user)
        return Redirect303(_next_url(request, body.get("next")))


class LogoutView(SamepageView):
    def post(self, request, fmt=None):
        logout(request)
        return Redirect303("/")


DEMO_LANDING = {
    "org": "/e/evt_01/progress",
    "admin": "/e/evt_01/progress",
    "jdg08": "/e/evt_01/judge/batches",
    "jdg03": "/e/evt_01/judge/batches",
    "priya1": "/e/evt_01/projects",
    "control": "/e/evt_02/projects",
}


class DemoEnterView(SamepageView):
    """Demo mode only. GET shows a button; the POST (with a CSRF token) signs the browser in.

    A GET never changes who is signed in, so an image tag on another site cannot do it.
    """

    def _principal(self, slug):
        if not settings.DEMO_MODE:
            raise NotFound("Not found.")
        spec = PRINCIPALS.get(slug)
        if spec is None:
            raise NotFound("Not found.")
        user = Person.objects.filter(id=spec["id"]).first()
        if user is None:
            raise NotFound("Not found.")
        return spec, user

    def get(self, request, slug, fmt=None):
        spec, _user = self._principal(slug)
        response = render(
            request,
            "demo_enter.html",
            {"page_title": "Demo sign-in", "slug": slug, "spec": spec, "landing": DEMO_LANDING.get(slug, "/")},
        )
        return annotate(response, request, fmt=fmt, public_cache=False)

    def post(self, request, slug, fmt=None):
        _spec, user = self._principal(slug)
        enforce_csrf(request)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Redirect303(DEMO_LANDING.get(slug, "/"))


class AccessView(SamepageView):
    action = "about.read"
    public_cache = True

    def get(self, request, fmt=None):
        from samepage.core.policy import describe

        items = describe()
        payload = {
            "title": "Who can see what",
            "event": None,
            "resource": "access",
            "columns": ["action", "who", "note"],
            "items": items,
            "count": len(items),
            "html_omitted": {},
            "download_csv": "/about/access.csv",
            "download_json": "/about/access.json",
        }
        return render_payload(request, payload, fmt, template="table.html", public_cache=True)


class EventView(SamepageView):
    action = "gallery.read"
    formats = ("html", "json")

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if event is None:
            raise NotFound("Unknown event.")
        roles = access.roles_of(request.principal, evt)
        payload = events.event_payload(event, roles=roles, principal=request.principal)
        return render_payload(request, payload, fmt, template="event.html", public_cache=False)


class EventSettingsView(SamepageView):
    """GET the organizer's control page for an event; POST (or PATCH .json) changes its settings."""

    action = "event.manage"
    formats = ("html", "json")

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if event is None:
            raise NotFound("Unknown event.")
        roles = access.roles_of(request.principal, evt)
        payload = events.event_payload(event, roles=roles, principal=request.principal)
        payload["title"] = f"Manage {event.name}"
        payload["people"] = events.people_payload(evt)["items"]
        payload["questions_text"] = "\n".join(
            q["label"] + (": " + ", ".join(q["choices"]) if q["kind"] == "choice" else "") + ("*" if q.get("required") else "")
            for q in event.custom_questions or []
        )
        payload["next_states"] = sorted(state for state in EVENT_MACHINE.get(event.state, set()) if state != "published")
        return render_payload(request, payload, fmt, template="event_settings.html")

    def post(self, request, evt, fmt=None):
        event = events.update(evt, request.principal, _body(request))
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/settings",
            payload={"id": event.id, "updated": True},
            status=200,
            location=f"/e/{evt}.json",
        )

    def patch(self, request, evt, fmt=None):
        return self.post(request, evt, fmt)


class EventStateView(SamepageView):
    action = "event.manage"
    formats = ("html", "json")

    def post(self, request, evt, fmt=None):
        event = events.set_state(evt, request.principal, _body(request).get("state"))
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/settings",
            payload={"id": event.id, "state": event.state},
            status=200,
            location=f"/e/{evt}.json",
        )


class CriteriaView(SamepageView):
    """The rubric. Anyone may read it (judges and teams should know how they are scored)."""

    action = "gallery.read"
    write_action = "event.manage"

    def get(self, request, evt, fmt=None):
        if not Event.objects.filter(id=evt).exists():
            raise NotFound("Unknown event.")
        items = events.criteria_rows(evt)
        rows = [
            {
                "key": row["key"],
                "label": row["label"],
                "weight": row["weight"],
                "track_overrides": " ".join(f"{track}={weight}" for track, weight in sorted(row["track_overrides"].items())),
            }
            for row in items
        ]
        payload = {
            "title": "Rubric",
            "event": evt,
            "resource": "criteria",
            "columns": ["key", "label", "weight", "track_overrides"],
            "items": rows,
            "criteria": items,
            "count": len(rows),
            "download_csv": f"/e/{evt}/criteria.csv",
            "download_json": f"/e/{evt}/criteria.json",
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="table.html")

    def post(self, request, evt, fmt=None):
        criteria = events.set_criteria(evt, request.principal, _body(request))
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/settings#rubric",
            payload={"criteria": criteria},
            status=200,
            location=f"/e/{evt}/criteria.json",
        )


class PeopleView(SamepageView):
    action = "people.read"
    write_action = "event.manage"

    def get(self, request, evt, fmt=None):
        if not Event.objects.filter(id=evt).exists():
            raise NotFound("Unknown event.")
        return render_payload(request, events.people_payload(evt), fmt, template="table.html")

    def post(self, request, evt, fmt=None):
        result = events.add_person(evt, request.principal, _body(request))
        if _wants_html(request, fmt):
            # The set-password link is shown once, so the browser gets a page, not a redirect.
            return render_payload(
                request,
                {
                    "title": "Added",
                    "event": evt,
                    "resource": "people-added",
                    "result": result,
                    "columns": [],
                    "items": [],
                    "count": 0,
                    "html_omitted": {},
                },
                "html",
                template="link_once.html",
                status=201,
            )
        return _json(request, result, 201, f"/e/{evt}/people.json", fmt)


class PasswordLinkIssueView(SamepageView):
    action = "event.manage"
    formats = ("html", "json")

    def post(self, request, evt, person, fmt=None):
        link = events.password_link(evt, request.principal, person)
        result = {"person_id": person, "password_link": link}
        if _wants_html(request, fmt):
            return render_payload(
                request,
                {"title": "Password link", "event": evt, "result": result, "columns": [], "items": [], "count": 0, "html_omitted": {}},
                "html",
                template="link_once.html",
                status=201,
            )
        return _json(request, result, 201, f"/e/{evt}/people.json", fmt)


class ProjectsView(SamepageView):
    action = "gallery.read"
    formats = ("html", "json", "csv")

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if event is None:
            raise NotFound("Unknown event.")
        roles = access.roles_of(request.principal, evt)
        staff = bool(roles & {"organizer", "admin"})
        query = request.GET.copy()
        if not staff:
            query.pop("state", None)
            query.pop("review", None)
            query.pop("duplicate", None)
        include = staff and query.get("state") in {"all", "withdrawn"}
        payload = ledger.project_rows(
            evt,
            include_withdrawn=include or query.get("state") == "withdrawn",
            query=query,
            paginate=negotiate(request, fmt) != "csv",
            include_drafts=staff and query.get("state") in {"all", "draft"},
        )
        payload["your_team"] = teams.my_team_id(evt, request.principal)
        payload["submissions_open"] = event.state == "open" and not is_closed(db_now(), event.submissions_close)
        if not staff:
            payload["items"] = [row for row in payload["items"] if row["state"] != "withdrawn"] if query.get("state") != "withdrawn" else payload["items"]
        # Blind judging: the same fields leave HTML, JSON and CSV, decided by the policy table.
        hidden = hidden_fields(roles, blind=event.blind_judging) & {"team_id", "team_name"}
        if hidden:
            payload["items"] = [{k: v for k, v in row.items() if k not in hidden} for row in payload["items"]]
            payload["columns"] = [column for column in payload["columns"] if column not in hidden]
            payload["html_omitted"] = {
                **payload.get("html_omitted", {}),
                **{field: "blind judging is on" for field in sorted(hidden)},
            }
        return render_payload(
            request,
            payload,
            fmt,
            template="gallery.html",
            public_cache=request.principal is None,
        )

    def post(self, request, evt, fmt=None):
        # Re-check the write action. GET on this URL is public; POST is not.
        access.require(request.principal, "submission.create", event_id=evt)
        body = _body(request)
        created = submissions.create(evt, request.principal, body)
        location = f"/e/{evt}/projects/{created.id}"
        return _done(
            request,
            fmt,
            html_to=location,
            payload={"id": created.id, "url": location + ".json", "title": created.title, "state": created.state},
            status=201,
            location=location + ".json",
        )


class ProjectFormView(SamepageView):
    """The HTML form for a new submission (prj is None) or for editing one."""

    action = "submission.update"
    formats = ("html",)

    def get(self, request, evt, prj=None, fmt=None):
        payload = submissions.form_payload(evt, request.principal, prj)
        return render_payload(request, payload, fmt, template="submission_form.html")


class ProjectView(SamepageView):
    action = "project.read"
    write_action = "submission.update"
    formats = ("html", "json")

    def get(self, request, evt, prj, fmt=None):
        roles = access.roles_of(request.principal, evt)
        payload = submissions.detail(evt, prj, principal=request.principal, roles=roles)
        return render_payload(request, payload, fmt, template="project.html", public_cache=request.principal is None)

    def post(self, request, evt, prj, fmt=None):
        submission = submissions.update(evt, prj, request.principal, _body(request))
        location = f"/e/{evt}/projects/{submission.id}"
        return _done(
            request,
            fmt,
            html_to=location,
            payload={"id": submission.id, "state": submission.state, "version": submission.version},
            status=200,
            location=location + ".json",
        )

    def patch(self, request, evt, prj, fmt=None):
        return self.post(request, evt, prj, fmt)


class ProjectSubmitView(SamepageView):
    action = "submission.update"
    formats = ("html", "json")

    def post(self, request, evt, prj, fmt=None):
        submission = submissions.submit(evt, prj, request.principal)
        location = f"/e/{evt}/projects/{submission.id}"
        return _done(
            request,
            fmt,
            html_to=location,
            payload={"id": submission.id, "state": submission.state, "submitted_at": submission.submitted_at.isoformat()},
            status=200,
            location=location + ".json",
        )


class ProjectWithdrawView(SamepageView):
    action = "submission.withdraw"
    formats = ("html", "json")

    def post(self, request, evt, prj, fmt=None):
        submission = submissions.withdraw(evt, prj, request.principal, _body(request))
        location = f"/e/{evt}/projects/{submission.id}"
        return _done(
            request,
            fmt,
            html_to=location,
            payload={"id": submission.id, "state": submission.state},
            status=200,
            location=location + ".json",
        )


class MediaUploadView(SamepageView):
    action = "submission.update"
    formats = ("html", "json")

    def post(self, request, evt, prj, fmt=None):
        kind = request.data.get("kind") if hasattr(request.data, "get") else None
        media = submissions.add_media(evt, prj, request.principal, request.FILES.get("file"), kind or "gallery")
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/projects/{prj}/edit",
            payload={"id": media.id, "kind": media.kind, "url": submissions.media_url(evt, prj, media.id), "sha256": media.sha256},
            status=201,
            location=submissions.media_url(evt, prj, media.id),
        )


class MediaView(SamepageView):
    """The image bytes, with the type sniffed at upload. Same visibility as the project."""

    action = "project.read"
    formats = ("html",)

    def get(self, request, evt, prj, media, fmt=None):
        roles = access.roles_of(request.principal, evt)
        row = submissions.media_file(evt, prj, media, principal=request.principal, roles=roles)
        response = HttpResponse(bytes(row.data), content_type=row.content_type)
        response["Content-Length"] = str(row.size)
        response["ETag"] = f'"{row.sha256}"'
        response = annotate(response, request, fmt="img", public_cache=request.principal is None)
        # An image never runs script, even if a browser were talked into rendering it as a page.
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


class MediaDeleteView(SamepageView):
    action = "submission.update"
    formats = ("html", "json")

    def post(self, request, evt, prj, media, fmt=None):
        submissions.remove_media(evt, prj, media, request.principal)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/projects/{prj}/edit",
            payload={"removed": media},
            status=200,
            location=f"/e/{evt}/projects/{prj}.json",
        )


class TeamsView(SamepageView):
    """GET: every team (organizers). POST: start a team and become its first member."""

    action = "people.read"
    write_action = "team.create"

    def get(self, request, evt, fmt=None):
        if not Event.objects.filter(id=evt).exists():
            raise NotFound("Unknown event.")
        return render_payload(request, teams.teams_payload(evt), fmt, template="table.html")

    def post(self, request, evt, fmt=None):
        team = teams.create(evt, request.principal, _body(request))
        location = f"/e/{evt}/teams/{team.id}"
        return _done(
            request,
            fmt,
            html_to=location,
            payload={"id": team.id, "name": team.name, "url": location + ".json"},
            status=201,
            location=location + ".json",
        )


class TeamView(SamepageView):
    action = "team.read"
    formats = ("html", "json")

    def get(self, request, evt, team, fmt=None):
        payload = teams.team_payload(evt, team, request.principal)
        return render_payload(request, payload, fmt, template="team.html")


class TeamInvitesView(SamepageView):
    action = "team.manage"
    formats = ("html", "json")

    def post(self, request, evt, team, fmt=None):
        result = teams.create_invite(evt, team, request.principal, _body(request))
        if _wants_html(request, fmt):
            return render_payload(
                request,
                {"title": "Invite link", "event": evt, "result": result, "columns": [], "items": [], "count": 0, "html_omitted": {}},
                "html",
                template="link_once.html",
                status=201,
            )
        return _json(request, result, 201, f"/e/{evt}/teams/{team}.json", fmt)


class InviteRevokeView(SamepageView):
    action = "team.manage"
    formats = ("html", "json")

    def post(self, request, evt, team, invite, fmt=None):
        teams.revoke_invite(evt, team, invite, request.principal)
        return _done(
            request, fmt, html_to=f"/e/{evt}/teams/{team}", payload={"revoked": invite}, status=200, location=f"/e/{evt}/teams/{team}.json"
        )


class TeamLeaveView(SamepageView):
    action = "team.read"
    formats = ("html", "json")

    def post(self, request, evt, team, fmt=None):
        teams.leave(evt, team, request.principal)
        return _done(request, fmt, html_to=f"/e/{evt}", payload={"left": team}, status=200, location=f"/e/{evt}.json")


class TeamRemoveView(SamepageView):
    action = "event.manage"
    formats = ("html", "json")

    def post(self, request, evt, team, person, fmt=None):
        teams.remove_member(evt, team, person, request.principal)
        return _done(
            request, fmt, html_to=f"/e/{evt}/teams/{team}", payload={"removed": person}, status=200, location=f"/e/{evt}/teams/{team}.json"
        )


class JoinView(SamepageView):
    """GET: which team the link is for. POST: join it (signed in)."""

    formats = ("html", "json")

    def get(self, request, token, fmt=None):
        payload = teams.invite_preview(token)
        payload["path"] = f"/join/{token}"
        return render_payload(request, payload, fmt, template="join.html")

    def post(self, request, token, fmt=None):
        preview = teams.invite_preview(token)
        access.require(request.principal, "invite.accept", event_id=preview["event"])
        team = teams.accept(token, request.principal)
        location = f"/e/{team.event_id}/teams/{team.id}"
        return _done(
            request, fmt, html_to=location, payload={"team": team.id, "joined": True}, status=200, location=location + ".json"
        )


class AcceptRoleView(SamepageView):
    """A judge or organizer role offered to an existing account. GET: what the link offers.
    POST: the invited account, signed in, accepts it; any other account is refused."""

    formats = ("html", "json")
    write_action = "role.accept"

    def get(self, request, token, fmt=None):
        payload = events.role_invite_preview(token, request.principal)
        payload["path"] = f"/accept/{token}"
        return render_payload(request, payload, fmt, template="accept.html")

    def post(self, request, token, fmt=None):
        result = events.accept_role_invite(token, request.principal)
        return _done(request, fmt, html_to="/account", payload=result, status=200, location=f"/e/{result['event']}.json")


class SignupView(SamepageView):
    """Create an account. HTML only, like /login: it starts a browser session."""

    throttle_classes = [LoginThrottle]
    throttle_scope = "login"

    def get(self, request, fmt=None):
        if request.principal is not None:
            return Redirect303(_next_url(request, request.GET.get("next")))
        response = render(
            request,
            "signup.html",
            {"page_title": "Create an account", "next": _next_url(request, request.GET.get("next"))},
        )
        return annotate(response, request, fmt=fmt, public_cache=False)

    def post(self, request, fmt=None):
        enforce_csrf(request)
        body = _body(request)
        person = accounts.signup(body)
        login(request, person, backend="django.contrib.auth.backends.ModelBackend")
        return Redirect303(_next_url(request, body.get("next")))


class PasswordLinkView(SamepageView):
    """A one-time link from an organizer: choose a password, then you are signed in."""

    throttle_classes = [LoginThrottle]
    throttle_scope = "login"

    def get(self, request, token, fmt=None):
        info = accounts.password_link_preview(token)
        response = render(request, "password_set.html", {"page_title": "Choose a password", "info": info, "token": token})
        return annotate(response, request, fmt=fmt, public_cache=False)

    def post(self, request, token, fmt=None):
        enforce_csrf(request)
        person = accounts.use_password_link(token, _body(request))
        login(request, person, backend="django.contrib.auth.backends.ModelBackend")
        return Redirect303("/account")


class AccountView(SamepageView):
    """Your roles and teams in every event, and changing your password."""

    action = "account.manage"
    formats = ("html", "json")

    def get(self, request, fmt=None):
        person = request.principal
        grants = RoleGrant.objects.filter(person=person).select_related("event").order_by("event_id", "role")
        team_of = dict(TeamMember.objects.filter(person=person).values_list("event_id", "team_id"))
        items = [
            {"event_id": row.event_id, "event": row.event.name, "role": row.role, "team_id": team_of.get(row.event_id, "")}
            for row in grants
        ]
        payload = {
            "title": "Your account",
            "event": None,
            "resource": "account",
            "id": person.id,
            "email": person.email,
            "name": person.name,
            "is_admin": "true" if person.is_admin else "false",
            "columns": ["event_id", "event", "role", "team_id"],
            "items": items,
            "count": len(items),
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="account.html")

    def post(self, request, fmt=None):
        accounts.change_password(request.principal, _body(request))
        # Changing the password rotates the session hash; keep this browser signed in.
        from django.contrib.auth import update_session_auth_hash

        update_session_auth_hash(request._request, request.principal)
        return _done(request, fmt, html_to="/account", payload={"changed": True}, status=200, location="/account.json")


class ScoresView(SamepageView):
    action = "scores.read_ledger"

    def get(self, request, evt, fmt=None):
        payload = ledger.score_payload(evt, request.GET)
        return render_payload(request, payload, fmt, template="table.html")


class OwnScoresView(SamepageView):
    action = "scores.read_own"

    def get(self, request, evt, fmt=None):
        payload = ledger.score_payload(evt, {"judge": request.principal.id})
        payload["title"] = "Your scores"
        payload["download_csv"] = f"/e/{evt}/judges/me/scores.csv"
        payload["download_json"] = f"/e/{evt}/judges/me/scores.json"
        return render_payload(request, payload, fmt, template="table.html")


class NamedScoresView(SamepageView):
    action = "scores.read_named"

    def get(self, request, evt, jdg, fmt=None):
        # The policy already compared jdg to the principal. Loading the rows is allowed; an id
        # that never judged this event is 404 for staff rather than an empty table.
        is_judge = RoleGrant.objects.filter(event_id=evt, person_id=jdg, role="judge").exists()
        if not is_judge and not Assignment.objects.filter(judge_id=jdg, submission__event_id=evt).exists():
            raise NotFound("Unknown judge.")
        payload = ledger.score_payload(evt, {"judge": jdg})
        payload["title"] = f"Scores by {jdg}"
        payload["download_csv"] = f"/e/{evt}/judges/{jdg}/scores.csv"
        payload["download_json"] = f"/e/{evt}/judges/{jdg}/scores.json"
        return render_payload(request, payload, fmt, template="table.html")


class ProgressView(SamepageView):
    action = "progress.read"

    def get(self, request, evt, fmt=None):
        payload = ledger.progress_payload(evt)
        return render_payload(request, payload, fmt, template="progress.html")


class ResultsView(SamepageView):
    action = "results.read"

    def get(self, request, evt, fmt=None):
        payload = results.results_payload(evt)
        published = payload.get("published")
        anonymous = request.principal is None and not request.META.get("HTTP_AUTHORIZATION")
        return render_payload(
            request,
            payload,
            fmt,
            template="results.html",
            public_cache=bool(published and anonymous),
        )


class PublishView(SamepageView):
    action = "publish"
    formats = ("html", "json")

    def post(self, request, evt, fmt=None):
        results.publish(evt, request.principal)
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/results")
        return _json(request, {"published": True}, 200, f"/e/{evt}/results.json", fmt)


class LabView(SamepageView):
    action = "normalization.read"

    def get(self, request, evt, table=None, fmt=None):
        payload = results.lab_payload(evt, table)
        template = "table.html" if table else "lab.html"
        return render_payload(request, payload, fmt, template=template)


class DuplicatesView(SamepageView):
    action = "duplicates.read"

    def get(self, request, evt, dup=None, fmt=None):
        if dup:
            payload = duplicates.detail_payload(evt, dup)
            return render_payload(request, payload, fmt, template="duplicate.html")
        payload = duplicates.list_payload(evt)
        return render_payload(request, payload, fmt, template="table.html")


class DuplicateConfirmView(SamepageView):
    action = "duplicates.resolve"
    formats = ("html", "json")

    def post(self, request, evt, dup, fmt=None):
        resolution = _body(request).get("resolution") or None
        if resolution is not None and not isinstance(resolution, str):
            raise Unprocessable({"resolution": "choose keep_latest or merge"})
        duplicates.confirm(evt, dup, request.principal.id, resolution=resolution)
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/duplicates/{dup}")
        return _json(request, {"confirmed": dup, "resolution": resolution or "keep_latest"}, 200, f"/e/{evt}/duplicates/{dup}.json", fmt)


class AuditView(SamepageView):
    action = "audit.read"

    def get(self, request, evt, fmt=None):
        from samepage.apps.portal.models import AuditEvent

        rows = AuditEvent.objects.filter(event_id=evt).order_by("seq")
        items = [
            {
                "seq": row.seq,
                "actor": row.actor,
                "action": row.action,
                "object": row.object_ref,
                "at": row.at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "hash": row.hash[:16],
            }
            for row in rows
        ]
        check = verify(evt)
        payload = {
            "title": "Audit",
            "event": evt,
            "resource": "audit",
            "columns": ["seq", "actor", "action", "object", "at", "hash"],
            "items": items,
            "count": len(items),
            "chain_ok": "true" if check["ok"] else "false",
            "chain_detail": check["detail"],
            "download_csv": f"/e/{evt}/audit.csv",
            "download_json": f"/e/{evt}/audit.json",
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="audit.html")


class AssignmentListView(SamepageView):
    action = "assignment.read"

    def get(self, request, evt, fmt=None):
        runs = AssignmentRun.objects.filter(event_id=evt).order_by("created_at")
        items = [{"id": row.id, "kind": row.kind, "seed": row.seed} for row in runs]
        payload = {
            "title": "Assignment runs",
            "event": evt,
            "columns": ["id", "kind", "seed"],
            "items": items,
            "count": len(items),
            "download_csv": f"/e/{evt}/assignment-runs.csv",
            "download_json": f"/e/{evt}/assignment-runs.json",
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="table.html")

    def post(self, request, evt, fmt=None):
        access.require(request.principal, "assignment.run", event_id=evt)
        body = _body(request)
        kind = str(body.get("kind") or "dry_run").strip()
        if kind == "topup":
            run = judging.topup(evt, actor=request.principal.id)
            payload = judging.run_payload(run)
        elif kind == "initial":
            run = judging.initial(evt, actor=request.principal.id, body=body)
            payload = judging.run_payload(run)
        elif kind == "dry_run":
            params = judging._run_params(body)
            payload = judging.dry_run(
                evt,
                actor=request.principal.id,
                seed=params.get("seed", 20260301),
                cap=params["cap"],
                coverage=params["coverage"],
            )
        else:
            raise Unprocessable({"kind": "choose dry_run, initial or topup"})
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/assignment-runs/{payload['id']}")
        return _json(request, {"id": payload["id"], "kind": kind}, 201, f"/e/{evt}/assignment-runs/{payload['id']}.json", fmt)


class AssignmentRunView(SamepageView):
    action = "assignment.read"

    def get(self, request, evt, run, fmt=None):
        row = AssignmentRun.objects.filter(event_id=evt, id=run).first()
        if row is None:
            raise NotFound("Unknown run.")
        return render_payload(request, judging.run_payload(row), fmt, template="run.html")


class AbandonView(SamepageView):
    action = "assignment.run"
    formats = ("html", "json")

    def post(self, request, evt, batch, fmt=None):
        judging.abandon(evt, batch, request.principal.id)
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/progress")
        return _json(request, {"abandoned": batch}, 200, f"/e/{evt}/progress.json", fmt)


class AssignmentsView(SamepageView):
    """Every judge-project assignment (organizers), and assigning one by hand."""

    action = "assignment.read"
    write_action = "assignment.run"

    def get(self, request, evt, fmt=None):
        if not Event.objects.filter(id=evt).exists():
            raise NotFound("Unknown event.")
        return render_payload(request, judging.assignments_payload(evt), fmt, template="assignments.html")

    def post(self, request, evt, fmt=None):
        run = judging.manual(evt, actor=request.principal.id, body=_body(request))
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/progress",
            payload={"id": run.id, "kind": run.kind, "assignments": run.report.get("assignments", [])},
            status=201,
            location=f"/e/{evt}/assignment-runs/{run.id}.json",
        )


class UnlockView(SamepageView):
    action = "score.unlock"
    formats = ("html", "json")

    def post(self, request, evt, jdg, prj, fmt=None):
        result = judging.unlock(evt, actor=request.principal.id, judge_id=jdg, project_id=prj, body=_body(request))
        return _done(request, fmt, html_to=f"/e/{evt}/progress", payload=result, status=200, location=f"/e/{evt}/scores.json")


class JudgeBatchesView(SamepageView):
    action = "judge.console"

    def get(self, request, evt, fmt=None):
        payload = judging.my_batches(evt, request.principal.id)
        return render_payload(request, payload, fmt, template="batches.html")


class ConsoleView(SamepageView):
    action = "judge.console"
    formats = ("html", "json")

    def get(self, request, evt, prj, fmt=None):
        payload = judging.console_payload(evt, request.principal.id, prj)
        return render_payload(request, payload, fmt, template="console.html")


class ConsoleSaveView(SamepageView):
    action = "judge.score"
    formats = ("html", "json")

    def post(self, request, evt, prj, fmt=None):
        body = _body(request)
        final = str(body.get("final") or "").lower() in {"1", "true", "on"}
        result = judging.save_scores(evt, request.principal, prj, body, final=final)
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/judge/assignments/{prj}")
        status = 200 if not result.get("saved", True) else 201
        return _json(request, result, status, f"/e/{evt}/judge/assignments/{prj}.json", fmt)


class FinalizeView(SamepageView):
    action = "judge.score"
    formats = ("html", "json")

    def post(self, request, evt, prj, fmt=None):
        # _body flattens a form post, so c_quality=4 arrives as "4", not ["4"].
        body = dict(_body(request))
        body["final"] = True
        result = judging.save_scores(evt, request.principal, prj, body, final=True)
        if _wants_html(request, fmt):
            return Redirect303(f"/e/{evt}/judge/assignments/{prj}")
        return _json(request, result, 200, f"/e/{evt}/judge/assignments/{prj}.json", fmt)


class VotingView(SamepageView):
    action = "voting.read"
    write_action = "voting.vote"
    throttle_classes = [BallotThrottle]

    def _resolve_voter(self, request, evt):
        if getattr(request, "principal", None):
            return "account", request.principal, "", "", str(request.principal.id)
        if request.session.get("voting_email"):
            email = request.session["voting_email"]
            return "email", None, "", email, email
        token = request.session.get("voting_open_token")
        if token or request.session.session_key:
            if not request.session.session_key:
                request.session.save()
            key = request.session.session_key
            return "open", None, key, "", key
        return "open", None, "", "", "anon"

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        config = voting.get_or_create_config(event)
        vtype, person, sess_key, email, voter_key = self._resolve_voter(request, evt)

        channel = "public"
        is_excluded = False
        reason = ""
        if vtype == "account" and person:
            if event.submissions_close and person.created_at > event.submissions_close:
                is_excluded = True
                reason = "account_created_after_submission_deadline"
            if TeamMember.objects.filter(event=event, person=person).exists():
                channel = "participants"
            else:
                channel = "public"

        ballot = None
        if vtype == "account" and person:
            ballot = Ballot.objects.filter(event=event, person=person).first()
        elif vtype == "email" and email:
            ballot = Ballot.objects.filter(event=event, voter_email=email).first()
        elif vtype == "open" and sess_key:
            ballot = Ballot.objects.filter(event=event, session_key=sess_key).first()

        existing_votes = {}
        if ballot:
            existing_votes = {line.submission_id: line.credits for line in ballot.lines.all()}

        submissions = voting.get_projects_for_voter(event, voter_key)
        items = [
            {
                "project_id": s.id,
                "title": s.title,
                "tagline": s.tagline,
                "credits": existing_votes.get(s.id, 0),
            }
            for s in submissions
        ]

        payload = {
            "title": f"Community Voting · {event.name}",
            "resource": "voting",
            "event": evt,
            "state": config.state,
            "credit_budget": config.credit_budget,
            "opens_at": config.opens_at.isoformat() if config.opens_at else None,
            "closes_at": config.closes_at.isoformat() if config.closes_at else None,
            "allow_accounts": config.allow_accounts,
            "allow_open": config.allow_open,
            "allow_email": config.allow_email,
            "voter": {
                "type": vtype,
                "channel": channel,
                "excluded": is_excluded,
                "exclusion_reason": reason,
            },
            "credits_spent": ballot.credits_spent if ballot else 0,
            "columns": ["project_id", "title", "credits"],
            "items": items,
            "count": len(items),
            "download_csv": f"/e/{evt}/voting.csv",
            "download_json": f"/e/{evt}/voting.json",
        }
        return render_payload(request, payload, fmt, template="voting.html")

    def post(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        body = _body(request)
        vtype, person, sess_key, email, _ = self._resolve_voter(request, evt)

        # Parse votes
        votes = {}
        if "votes" in body and isinstance(body["votes"], dict):
            votes = {k: int(v) for k, v in body["votes"].items() if int(v) > 0}
        else:
            for k, v in body.items():
                if k.startswith("credits_"):
                    pid = k[len("credits_") :]
                    try:
                        cr = int(v)
                        if cr > 0:
                            votes[pid] = cr
                    except (ValueError, TypeError):
                        pass

        client_ip = request.META.get("REMOTE_ADDR")
        ballot = voting.cast_ballot(
            event,
            vtype,
            votes,
            person=person,
            session_key=sess_key,
            voter_email=email,
            client_ip=client_ip,
        )
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/voting",
            payload={
                "ok": True,
                "ballot_id": ballot.id,
                "credits_spent": ballot.credits_spent,
                "channel": ballot.channel,
                "excluded": ballot.excluded,
            },
            status=200,
            location=f"/e/{evt}/voting.json",
        )


class VotingSettingsView(SamepageView):
    formats = ("html", "json")
    action = "voting.manage"
    write_action = "voting.manage"

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        config = voting.get_or_create_config(event)
        open_url = f"/vote/{config.open_token}" if config.open_token else ""
        payload = {
            "title": f"Voting Settings · {event.name}",
            "resource": "voting_settings",
            "event": evt,
            "state": config.state,
            "credit_budget": config.credit_budget,
            "opens_at": config.opens_at.isoformat() if config.opens_at else "",
            "closes_at": config.closes_at.isoformat() if config.closes_at else "",
            "allow_accounts": config.allow_accounts,
            "allow_open": config.allow_open,
            "open_url": open_url,
            "allow_email": config.allow_email,
            "download_json": f"/e/{evt}/voting/settings.json",
        }
        return render_payload(request, payload, fmt, template="voting_settings.html")

    def post(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        body = _body(request)
        params = {}
        if "credit_budget" in body:
            params["credit_budget"] = body["credit_budget"]
        if "state" in body:
            params["state"] = body["state"]
        if "allow_accounts" in body:
            params["allow_accounts"] = str(body["allow_accounts"]).lower() in {"1", "true", "on"}
        if "allow_open" in body:
            params["allow_open"] = str(body["allow_open"]).lower() in {"1", "true", "on"}
        if "allow_email" in body:
            params["allow_email"] = str(body["allow_email"]).lower() in {"1", "true", "on"}
        if "opens_at" in body:
            v = body["opens_at"]
            params["opens_at"] = timezone.datetime.fromisoformat(v) if v else None
        if "closes_at" in body:
            v = body["closes_at"]
            params["closes_at"] = timezone.datetime.fromisoformat(v) if v else None

        actor = request.principal.email if request.principal else "admin"
        config = voting.update_config(event, actor, **params)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/voting/settings",
            payload={"ok": True, "state": config.state, "credit_budget": config.credit_budget},
            status=200,
            location=f"/e/{evt}/voting/settings.json",
        )

    def patch(self, request, evt, fmt=None):
        return self.post(request, evt, fmt)


class VotingCloseView(SamepageView):
    formats = ("html", "json")
    action = "voting.close"
    write_action = "voting.close"

    def post(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        actor = request.principal.email if request.principal else "admin"
        tally = voting.close_and_count(event, actor)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/voting/tally",
            payload=tally.payload,
            status=200,
            location=f"/e/{evt}/voting/tally.json",
        )


class VotingTallyView(SamepageView):
    action = "voting.tally"

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        roles = access.roles_of(request.principal, evt)
        is_staff = bool(roles & {"organizer", "admin"})
        tally_data = voting.get_tally(event, is_staff)

        # If voting still in progress
        if tally_data.get("status") == "in_progress":
            payload = {
                "title": f"Voting Tally · {event.name}",
                "resource": "voting_tally",
                "event": evt,
                "status": "in_progress",
                "ballot_counts": tally_data.get("ballot_counts", {}),
                "message": tally_data.get("message", ""),
                "download_json": f"/e/{evt}/voting/tally.json",
            }
            return render_payload(request, payload, fmt, template="voting_tally.html")

        # Counted: build items for CSV
        csv_items = []
        for ch in ("participants", "public", "combined"):
            for row in tally_data.get(ch, []):
                csv_items.append({
                    "channel": ch,
                    "rank": row["rank"],
                    "project_id": row["project_id"],
                    "credits": row["credits"],
                    "influence": row["influence"],
                    "voters": row["voters"],
                })

        payload = {
            "title": f"Voting Tally · {event.name}",
            "resource": "voting_tally",
            "event": evt,
            "status": "counted",
            "ballot_counts": tally_data.get("ballot_counts", {}),
            "participants": tally_data.get("participants", []),
            "public": tally_data.get("public", []),
            "combined": tally_data.get("combined", []),
            "columns": ["channel", "rank", "project_id", "credits", "influence", "voters"],
            "items": csv_items,
            "count": len(csv_items),
            "download_csv": f"/e/{evt}/voting/tally.csv",
            "download_json": f"/e/{evt}/voting/tally.json",
        }
        return render_payload(request, payload, fmt, template="voting_tally.html")


class VotingRequestLinkView(SamepageView):
    formats = ("html", "json")
    action = "voting.read"
    write_action = "voting.read"
    throttle_classes = [MagicLinkThrottle]

    def post(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        body = _body(request)
        email = str(body.get("email", "")).strip().lower()
        if not email or "@" not in email:
            raise Unprocessable("A valid email address is required.")
        voting.request_magic_link(event, email, request.build_absolute_uri("/"))
        # S1: Magic link is NEVER shown on the voter's screen.
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/voting",
            payload={"ok": True, "message": "A magic link has been sent to your email (valid for 15 minutes)."},
            status=200,
            location=f"/e/{evt}/voting.json",
        )


class VoteOpenLinkView(SamepageView):
    action = "voting.read"

    def get(self, request, token, fmt=None):
        # 1. Check if token is a magic link
        token_sha = hashlib.sha256(token.encode("utf-8")).hexdigest()
        outbox = MailOutbox.objects.filter(token_sha256=token_sha).first()
        if outbox:
            event, email = voting.redeem_magic_link(token)
            request.session["voting_email"] = email
            request.session["voting_event"] = event.id
            return Redirect303(f"/e/{event.id}/voting")

        # 2. Check if token is an open voting token
        config = VotingConfig.objects.filter(open_token=token, allow_open=True).first()
        if config:
            request.session["voting_open_token"] = token
            request.session["voting_event"] = config.event_id
            if not request.session.session_key:
                request.session.save()
            return Redirect303(f"/e/{config.event_id}/voting")

        raise NotFound("Invalid or expired voting link.")


class MailOutboxView(SamepageView):
    action = "outbox.read"

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        rows = MailOutbox.objects.filter(event=event).order_by("-created_at")
        items = [
            {
                "recipient_email": r.recipient_email,
                "subject": r.subject,
                "magic_url": r.magic_url,
                "expires_at": r.expires_at.isoformat(),
                "used_at": r.used_at.isoformat() if r.used_at else "",
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        payload = {
            "title": f"Mail Outbox · {event.name}",
            "resource": "mail_outbox",
            "event": evt,
            "columns": ["recipient_email", "subject", "magic_url", "expires_at", "used_at", "created_at"],
            "items": items,
            "count": len(items),
            "demo_inbox": bool(settings.DEMO_MODE),
            "download_csv": f"/e/{evt}/outbox.csv",
            "download_json": f"/e/{evt}/outbox.json",
        }
        return render_payload(request, payload, fmt, template="outbox.html")


class ProjectCommentsView(SamepageView):
    action = "project.read"
    write_action = "comment.create"
    throttle_classes = [CommentThrottle]

    def get(self, request, evt, prj, fmt=None):
        submission = Submission.objects.filter(event_id=evt, id=prj).first()
        if not submission:
            raise NotFound("Unknown project.")
        items = comments.list_public_comments(submission)
        payload = {
            "title": f"Comments · {submission.title}",
            "resource": "comments",
            "event": evt,
            "project": prj,
            "columns": ["id", "author_name", "text", "created_at"],
            "items": items,
            "count": len(items),
            "download_csv": f"/e/{evt}/projects/{prj}/comments.csv",
            "download_json": f"/e/{evt}/projects/{prj}/comments.json",
        }
        return render_payload(request, payload, fmt, template="project.html")

    def post(self, request, evt, prj, fmt=None):
        submission = Submission.objects.filter(event_id=evt, id=prj).first()
        if not submission:
            raise NotFound("Unknown project.")
        body = _body(request)
        text = str(body.get("text", "")).strip()
        cmt = comments.post_comment(submission, request.principal, text)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/projects/{prj}",
            payload={"id": cmt.id, "state": "pending", "message": "Comment submitted for moderation."},
            status=201,
            location=f"/e/{evt}/projects/{prj}/comments.json",
        )


class CommentsQueueView(SamepageView):
    action = "comments.moderate"

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if not event:
            raise NotFound("Unknown event.")
        items = comments.list_moderation_queue(event)
        payload = {
            "title": f"Comments Queue · {event.name}",
            "resource": "comments_queue",
            "event": evt,
            "columns": ["id", "project_id", "project_title", "author_email", "text", "state", "created_at", "reviewed_by", "reviewed_at"],
            "items": items,
            "count": len(items),
            "download_csv": f"/e/{evt}/comments.csv",
            "download_json": f"/e/{evt}/comments.json",
        }
        return render_payload(request, payload, fmt, template="comments_queue.html")


class CommentApproveView(SamepageView):
    formats = ("html", "json")
    action = "comments.moderate"
    write_action = "comments.moderate"

    def post(self, request, evt, cmt, fmt=None):
        comments.approve_comment(cmt, request.principal)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/comments",
            payload={"ok": True, "state": "approved"},
            status=200,
            location=f"/e/{evt}/comments.json",
        )


class CommentRejectView(SamepageView):
    formats = ("html", "json")
    action = "comments.moderate"
    write_action = "comments.moderate"

    def post(self, request, evt, cmt, fmt=None):
        body = _body(request)
        reason = str(body.get("reason", "")).strip()
        comments.reject_comment(cmt, request.principal, reason=reason)
        return _done(
            request,
            fmt,
            html_to=f"/e/{evt}/comments",
            payload={"ok": True, "state": "rejected"},
            status=200,
            location=f"/e/{evt}/comments.json",
        )

