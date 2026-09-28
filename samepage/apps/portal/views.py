"""HTTP resources. Each one is a SamepageView. Writes call services and then pick HTML or JSON."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework.exceptions import NotFound

from samepage.apps.portal.models import AssignmentRun, Batch, Event, Person
from samepage.core.csrf import enforce_csrf
from samepage.core.errors import Unprocessable, problem_response
from samepage.core.headers import annotate
from samepage.core.policy import hidden_fields
from samepage.core.throttles import LoginThrottle
from samepage.core.renderers import negotiate, render_payload
from samepage.core.views import SamepageView
from samepage.domain.tokens import DEMO_PASSWORD, PRINCIPALS
from samepage.services import access, duplicates, judging, ledger, results, submissions
from samepage.services.audit import verify


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


def _body(request) -> dict:
    """The request body as one flat object. A form post keeps the last value of each field."""
    data = request.data
    if hasattr(data, "dict"):
        return data.dict()
    if isinstance(data, dict):
        return data
    raise Unprocessable("Expected an object.")


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

    def get(self, request, fmt=None):
        events = [
            {"id": row.id, "name": row.name, "state": row.state}
            for row in Event.objects.order_by("id")
        ]
        payload = {
            "title": "Samepage",
            "event": None,
            "pitch": "Every number on every page opens as the rows behind it.",
            "columns": ["id", "name", "state"],
            "items": events,
            "count": len(events),
            "html_omitted": {},
        }
        return render_payload(request, payload, fmt, template="home.html", public_cache=not request.principal)


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
        nxt = str(body.get("next") or "/")
        if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
            nxt = "/"
        return Redirect303(nxt)


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

    def get(self, request, evt, fmt=None):
        event = Event.objects.filter(id=evt).first()
        if event is None:
            raise NotFound("Unknown event.")
        payload = {
            "title": event.name,
            "event": event.id,
            "name": event.name,
            "state": event.state,
            "submissions_close": event.submissions_close.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "blind_judging": "true" if event.blind_judging else "false",
            "columns": ["id", "name", "state"],
            "items": [{"id": event.id, "name": event.name, "state": event.state}],
            "count": 1,
            "html_omitted": {},
            "download_json": f"/e/{event.id}.json",
        }
        return render_payload(request, payload, fmt, template="event.html", public_cache=False)


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
        include = staff and query.get("state") in {"all", "withdrawn"}
        payload = ledger.project_rows(
            evt,
            include_withdrawn=include or query.get("state") == "withdrawn",
            query=query,
            paginate=negotiate(request, fmt) != "csv",
        )
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
        body = request.data
        if not isinstance(body, dict):
            raise Unprocessable("Expected an object.")
        created = submissions.create(evt, request.principal, body)
        location = f"/e/{evt}/projects/{created.id}"
        if _wants_html(request, fmt):
            return Redirect303(location)
        return _json(
            request,
            {"id": created.id, "url": location + ".json", "title": created.title},
            201,
            location + ".json",
            fmt,
        )


class ProjectView(SamepageView):
    action = "project.read"
    formats = ("html", "json")

    def get(self, request, evt, prj, fmt=None):
        roles = access.roles_of(request.principal, evt)
        payload = submissions.detail(evt, prj, principal=request.principal, roles=roles)
        return render_payload(request, payload, fmt, template="project.html", public_cache=request.principal is None)


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
        # The policy already compared jdg to the principal. Loading the rows is allowed.
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
        kind = str(_body(request).get("kind") or "dry_run").strip()
        if kind == "topup":
            run = judging.topup(evt, actor=request.principal.id)
            payload = judging.run_payload(run)
        elif kind == "dry_run":
            payload = judging.dry_run(evt, actor=request.principal.id)
        else:
            raise Unprocessable({"kind": "choose dry_run or topup"})
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
