"""Sign-in throttle. Only POST /login counts, so run.py's GET routes can never see a 429."""

from __future__ import annotations

from rest_framework.throttling import ScopedRateThrottle


class LoginThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
