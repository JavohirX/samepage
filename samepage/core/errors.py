"""RFC 9457 for JSON and CSV. HTML gets a problem page, or the login form on 401."""

from __future__ import annotations

import json
import uuid

from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    ValidationError,
)
from rest_framework.views import exception_handler as drf_default

from samepage.core.headers import annotate
from samepage.core.renderers import negotiate

TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Content",
    500: "Internal Server Error",
}


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
    return annotate(response, request, fmt=fmt, public_cache=public_cache)


def exception_handler(exc, context):
    request = context["request"]
    fmt = context.get("kwargs", {}).get("fmt")
    if isinstance(exc, ValidationError) and not isinstance(exc, Unprocessable):
        # Field errors are 422. Parse errors stay 400 via ParseError.
        exc = Unprocessable(exc.detail)
    status = _status_of(exc)
    if status == 500 and not isinstance(exc, APIException):
        detail = "Something went wrong."
    else:
        detail = _detail_of(exc)
    # Returning HttpResponse skips DRF's renderer, which would turn a CSV 403 into a 500.
    return problem_response(request, status, detail, fmt=fmt)


def csrf_failure(request, reason=""):
    return problem_response(request, 403, "CSRF check failed.")


def handle_404(request, exception):
    return problem_response(request, 404, "Not found.")


def handle_500(request):
    return problem_response(request, 500, "Something went wrong.")
