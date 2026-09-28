"""Resolve a principal's roles, then ask the policy tables. No target row is loaded here."""

from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied

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
        published = Event.objects.filter(id=event_id, state__in=("published", "archived")).exists()
    target_is_self = bool(principal is not None and target and target == principal.id)
    if policy.allows(
        roles, action, target_is_self=target_is_self, published=published, signed_in=principal is not None
    ):
        if event_id and not roles & policy.STAFF and Event.objects.filter(id=event_id, state="draft").exists():
            # A draft event is its organizers' work in progress: to everyone else it does not exist yet,
            # by id as well as in the list. Checked after the policy, so the answer is the same as for
            # an id that was never created.
            raise NotFound("Unknown event.")
        return roles
    # Unpublished results are a refusal, including for anonymous visitors.
    # Other protected pages answer 401 so a browser gets the sign-in form.
    if principal is None and action != "results.read":
        raise NotAuthenticated("Sign in to continue.")
    raise PermissionDenied("You cannot do that.")
