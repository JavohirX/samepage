"""Resolve a principal's roles, then ask the policy tables. No target row is loaded here."""

from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated, PermissionDenied

from samepage.apps.portal.models import Event, RoleGrant
from samepage.core import policy


def roles_of(principal, event_id: str | None) -> set[str]:
    if principal is None:
        return {policy.VISITOR}
    roles = set()
    if getattr(principal, "is_admin", False):
        roles.add(policy.ADMIN)
    if event_id:
        roles.update(
            RoleGrant.objects.filter(person_id=principal.id, event_id=event_id).values_list("role", flat=True)
        )
    if not roles:
        roles.add(policy.VISITOR)
    return roles


def require(principal, action: str, *, event_id: str | None = None, target: str | None = None) -> set[str]:
    roles = roles_of(principal, event_id)
    published = False
    if action == "results.read" and event_id:
        published = Event.objects.filter(id=event_id, state="published").exists()
    target_is_self = bool(principal is not None and target and target == principal.id)
    if policy.allows(roles, action, target_is_self=target_is_self, published=published):
        return roles
    # Unpublished results are a refusal, including for anonymous visitors.
    # Other protected pages answer 401 so a browser gets the sign-in form.
    if principal is None and action != "results.read":
        raise NotAuthenticated("Sign in to continue.")
    raise PermissionDenied("You cannot do that.")
