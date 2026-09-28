"""RFC 9457 for JSON and CSV. HTML gets a problem page, or the login form on 401."""

from __future__ import annotations

import json
import logging
import uuid

from django.db import DatabaseError, IntegrityError
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.views import set_rollback

from samepage.core.headers import annotate
from samepage.core.renderers import negotiate
from samepage.domain.transitions import TransitionError

logger = logging.getLogger("samepage.errors")

TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    409: "Conflict",
    415: "Unsupported Media Type",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

SUFFIXES = ("html", "json", "csv")


def suffix_of(request) -> str | None:
    """The format a URL asks for by its suffix, for responses made before any view saw the URL."""
    last = request.path.rsplit("/", 1)[-1]
    _stem, dot, ext = last.rpartition(".")
    return ext if dot and ext in SUFFIXES else None


class Conflict(APIException):
    status_code = 409
    default_detail = "Conflict."
    default_code = "conflict"


class Unprocessable(APIException):
    status_code = 422
    default_detail = "The request could not be processed."
    default_code = "unprocessable"


def _status_of(exc) -> int:
    if isinstance(exc, Unprocessable):
        return 422
    if isinstance(exc, Conflict):
        return 409
    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        return 401
    if isinstance(exc, PermissionDenied):
        return 403
    if isinstance(exc, NotFound):
        return 404
    if isinstance(exc, ParseError):
        return 400
    if isinstance(exc, ValidationError):
        return 422
    if isinstance(exc, APIException):
        return int(exc.status_code)
    return 500


def _detail_of(exc) -> str:
    detail = getattr(exc, "detail", None)
    if detail is None:
        return "Something went wrong."
    if isinstance(detail, (list, dict)):
        return json.dumps(detail, default=str)
    return str(detail)


def problem_response(request, status: int, detail: str, *, fmt: str | None = None, public_cache: bool = False):
    chosen = negotiate(request, fmt if fmt is not None else getattr(request, "samepage_fmt", None))
    correlation = getattr(request, "correlation_id", "") or uuid.uuid4().hex[:16]
    title = TITLES.get(status, "Error")
    if chosen == "html" and status == 401:
        response = render(
            request,
            "login.html",
            {"error": detail, "page_title": "Sign in", "status": 401},
            status=401,
        )
        response["WWW-Authenticate"] = 'Bearer realm="samepage"'
        return annotate(response, request, fmt=fmt, public_cache=False)
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "correlation_id": correlation,
    }
    if chosen == "html":
        response = render(request, "problem.html", {"problem": body, "page_title": title}, status=status)
    else:
        response = HttpResponse(
            json.dumps(body),
            status=status,
            content_type="application/problem+json; charset=utf-8",
        )
    if status == 401:
        response["WWW-Authenticate"] = 'Bearer realm="samepage"'
    return annotate(response, request, fmt=fmt, public_cache=public_cache)


def _database_refusal(exc: DatabaseError) -> str | None:
    """A trigger refusal or a constraint violation is the client's conflict, not a server fault."""
    if isinstance(exc, IntegrityError):
        return "That conflicts with data that already exists."
    try:
        from psycopg import errors as pg_errors
    except ImportError:  # pragma: no cover - psycopg is a runtime dependency
        return None
    cause = exc.__cause__
    if isinstance(cause, pg_errors.RaiseException):
        # RAISE EXCEPTION text comes from our own triggers (migrations/0002_triggers.py).
        return cause.diag.message_primary or "Refused by a database rule."
    return None


def exception_handler(exc, context):
    request = context["request"]
    fmt = context.get("kwargs", {}).get("fmt")
    # Nothing a refused request wrote may be committed by ATOMIC_REQUESTS.
    set_rollback()
    if isinstance(exc, TransitionError):
        exc = Conflict(str(exc))
    elif isinstance(exc, DatabaseError):
        refusal = _database_refusal(exc)
        if refusal:
            exc = Conflict(refusal)
    if isinstance(exc, ValidationError) and not isinstance(exc, Unprocessable):
        # Field errors are 422. Parse errors stay 400 via ParseError.
        exc = Unprocessable(exc.detail)
    status = _status_of(exc)
    if status >= 500 and not isinstance(exc, APIException):
        detail = "Something went wrong."
        logger.error(
            "unhandled %s correlation_id=%s method=%s path=%s",
            type(exc).__name__,
            getattr(request, "correlation_id", ""),
            request.method,
            request.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        detail = _detail_of(exc)
    # Returning HttpResponse skips DRF's renderer, which would turn a CSV 403 into a 500.
    response = problem_response(request, status, detail, fmt=fmt)
    if isinstance(exc, Throttled) and exc.wait:
        response["Retry-After"] = str(int(exc.wait) + 1)
    return response


def csrf_failure(request, reason=""):
    return problem_response(request, 403, "CSRF check failed.", fmt=suffix_of(request))


def handle_404(request, exception):
    return problem_response(request, 404, "Not found.", fmt=suffix_of(request))


def handle_500(request):
    # django.request logs the traceback just before this runs. This line ties it to the page's reference.
    logger.error(
        "server error correlation_id=%s method=%s path=%s",
        getattr(request, "correlation_id", ""),
        request.method,
        request.path,
    )
    # A .json URL gets problem+json even when the failure (a database that is down) came before the view.
    return problem_response(request, 500, "Something went wrong.", fmt=suffix_of(request))
