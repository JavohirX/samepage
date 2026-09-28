"""CSRF for anonymous cookie writes.

DRF views are csrf_exempt, and SessionAuthentication checks CSRF only for a request that
is already signed in. Sign-in itself is a cookie write by an anonymous browser, so the
views that start a session call `enforce_csrf` themselves (login-CSRF otherwise).
"""

from __future__ import annotations

from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied


def enforce_csrf(request) -> None:
    django_request = getattr(request, "_request", request)
    check = CSRFCheck(lambda _request: None)
    check.process_request(django_request)
    reason = check.process_view(django_request, None, (), {})
    if reason:
        raise PermissionDenied("CSRF check failed.")
