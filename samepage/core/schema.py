"""Custom drf-spectacular AutoSchema for Samepage views (S11)."""

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import get_doc


class SamepageAutoSchema(AutoSchema):
    def get_description(self) -> str:
        method = getattr(self.view, self.method.lower(), None)
        action_doc = get_doc(method)
        view_doc = get_doc(self.view.__class__)
        return action_doc or view_doc or ""
