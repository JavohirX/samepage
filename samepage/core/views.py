"""SamepageView. Every URL resolves to a subclass. Policy runs before any target id is loaded."""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from samepage.core.auth import BearerAuthentication
from samepage.services.access import require


class SamepageView(APIView):
    authentication_classes = [BearerAuthentication, SessionAuthentication]
    permission_classes = [AllowAny]
    formats = ("html", "json", "csv")
    action = None
    # The action a POST, PATCH or DELETE needs, when it differs from what reading the URL needs.
    write_action = None
    html_omitted: dict[str, str] = {}
    public_cache = False

    def initial(self, request, *args, **kwargs):
        from rest_framework.exceptions import NotFound

        fmt = kwargs.get("fmt")
        if fmt is not None and fmt not in self.formats:
            raise NotFound("Unknown suffix.")
        request.samepage_fmt = fmt
        super().initial(request, *args, **kwargs)
        user = request.user
        request.principal = user if getattr(user, "is_authenticated", False) else None
        action = self.action
        if request.method not in ("GET", "HEAD", "OPTIONS") and self.write_action:
            action = self.write_action
        if action:
            require(
                request.principal,
                action,
                event_id=kwargs.get("evt"),
                target=kwargs.get("jdg"),
            )
