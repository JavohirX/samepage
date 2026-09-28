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
        if self.action:
            require(
                request.principal,
                self.action,
                event_id=kwargs.get("evt"),
                target=kwargs.get("jdg"),
            )
