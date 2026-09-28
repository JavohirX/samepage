"""SamepageView. Every URL resolves to a subclass. Policy runs before any target id is loaded."""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from samepage.core.auth import BearerAuthentication
from samepage.services.access import require


NUL_MESSAGE = "contains a NUL character"


def nul_field(value, name: str = "body") -> str | None:
    """The first field whose text holds a NUL character, else None.

    Postgres text cannot store U+0000, so such a value would fail at the database as a 500.
    A form or query string is a QueryDict (every value of every key); a JSON body is walked whole.
    """
    if isinstance(value, str):
        return name if "\x00" in value else None
    if hasattr(value, "lists"):
        for key, items in value.lists():
            found = nul_field(key, "field name") or nul_field(list(items), str(key))
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if "\x00" in key_text:
                return "field name"
            found = nul_field(item, key_text if name == "body" else f"{name}.{key_text}")
            if found:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            found = nul_field(item, name)
            if found:
                return found
    return None


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
        # After the policy, so a refused caller learns nothing new; before any view reads the query.
        field = nul_field(request.GET, "query")
        if field:
            from samepage.core.errors import Unprocessable

            raise Unprocessable({field: NUL_MESSAGE})
