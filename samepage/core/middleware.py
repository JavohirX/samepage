"""Request id, bearer CSRF bypass, and the headers that do not depend on the body."""

from __future__ import annotations

import uuid


class CorrelationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.correlation_id = uuid.uuid4().hex[:16]
        return self.get_response(request)


class BearerCSRFBypass:
    """Bearer requests are not cookie sessions, so CSRF does not apply to them."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get("HTTP_AUTHORIZATION", "").startswith("Bearer "):
            request._dont_enforce_csrf_checks = True
        elif request.path.startswith("/demo/enter/"):
            request._dont_enforce_csrf_checks = True
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("X-Content-Type-Options", "nosniff")
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault("X-Frame-Options", "DENY")
        response.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if getattr(request, "correlation_id", None):
            response.setdefault("X-Correlation-ID", request.correlation_id)
        return response
