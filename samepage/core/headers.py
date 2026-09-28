"""Cache, CORS and the correlation id. Credentialed and error responses are never stored."""

from __future__ import annotations

from django.conf import settings


def annotate(response, request, *, fmt: str | None, public_cache: bool):
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Frame-Options"] = "DENY"
    response["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    correlation = getattr(request, "correlation_id", "")
    if correlation:
        response["X-Correlation-ID"] = correlation
    authed = bool(
        request.META.get("HTTP_AUTHORIZATION")
        or request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    )
    if response.status_code >= 400 or authed or not public_cache:
        response["Cache-Control"] = "private, no-store"
    else:
        response["Cache-Control"] = "public, max-age=30"
        if request.method == "GET":
            response["Access-Control-Allow-Origin"] = "*"
    if not fmt:
        response["Vary"] = "Accept"
    return response
