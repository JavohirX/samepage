"""Sign-in throttle. Only POST /login counts, so run.py's GET routes can never see a 429.

The count lives in the Postgres-backed "throttle" cache, not in each worker's memory,
so two gunicorn workers still allow 10 attempts a minute per client, not 20.
"""

from __future__ import annotations

from django.core.cache import caches
from django.utils.connection import ConnectionProxy
from rest_framework.throttling import ScopedRateThrottle


class LoginThrottle(ScopedRateThrottle):
    # A proxy, like django.core.cache.cache: each thread resolves its own cache handle.
    cache = ConnectionProxy(caches, "throttle")

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
