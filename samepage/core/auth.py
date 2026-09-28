"""Bearer tokens. A present but invalid Authorization header is 401 and never falls back to a cookie.

Demo tokens (api_token.demo) are derived from a secret in this repository. They work only
in demo mode. Production also refuses to boot while one exists (ops/preflight.py).
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from samepage.apps.portal.models import ApiToken


class BearerAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header:
            return None
        scheme, _, token = header.partition(" ")
        if scheme != "Bearer" or not token:
            raise AuthenticationFailed("Authorization is not a bearer token.")
        digest = hashlib.sha256(token.encode()).hexdigest()
        row = (
            ApiToken.objects.filter(token_sha256=digest, revoked_at__isnull=True)
            .select_related("person")
            .first()
        )
        if row is None or not row.person.is_active:
            raise AuthenticationFailed("Invalid token.")
        if row.expires_at is not None and row.expires_at <= timezone.now():
            raise AuthenticationFailed("Token expired.")
        if row.demo and not settings.DEMO_MODE:
            raise AuthenticationFailed("Demo tokens are refused in production mode.")
        return (row.person, row)

    def authenticate_header(self, request):
        return "Bearer"
