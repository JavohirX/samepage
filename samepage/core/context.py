"""Shell context: demo mode and the signed-in person."""

from __future__ import annotations

from django.conf import settings


def shell(request):
    user = getattr(request, "user", None)
    me = user if user is not None and getattr(user, "is_authenticated", False) else None
    return {
        "demo_mode": settings.DEMO_MODE,
        "me": me,
        "public_url": settings.PUBLIC_URL,
    }
