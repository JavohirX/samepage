"""One policy source. Scope is derived from these tables, never stored beside them.

`allows` is pure: callers resolve roles and the target id before they ask.
The view still calls it before it loads the target row.
"""

from __future__ import annotations

VISITOR = "visitor"
PARTICIPANT = "participant"
JUDGE = "judge"
ORGANIZER = "organizer"
ADMIN = "admin"

EVERYONE = {VISITOR, PARTICIPANT, JUDGE, ORGANIZER, ADMIN}
STAFF = {ORGANIZER, ADMIN}
JUDGES = {JUDGE, ORGANIZER, ADMIN}

# Role × action. Admin is listed wherever an organizer is listed.
ACTION_POLICY = {
    "gallery.read": EVERYONE,
    "project.read": EVERYONE,
    "about.read": EVERYONE,
    "submission.create": {PARTICIPANT, ORGANIZER, ADMIN},
    "submission.update": {PARTICIPANT, ORGANIZER, ADMIN},
    "submission.withdraw": {PARTICIPANT, ORGANIZER, ADMIN},
    "scores.read_own": {JUDGE},
    "scores.read_named": JUDGES,
    "scores.read_ledger": STAFF,
    "progress.read": STAFF,
    "results.read": STAFF,
    "normalization.read": STAFF,
    "audit.read": STAFF,
    "duplicates.read": STAFF,
    "duplicates.resolve": STAFF,
    "assignment.read": STAFF,
    "assignment.run": STAFF,
    "event.manage": STAFF,
    "judge.console": {JUDGE},
    "judge.score": {JUDGE},
    "publish": STAFF,
    "invite.accept": {PARTICIPANT, JUDGE, ORGANIZER, ADMIN},
}

# Role × field → hidden. Blind mode adds team identity for judges at runtime.
FIELD_POLICY = {
    (VISITOR, "member_emails"): "hidden",
    (VISITOR, "score.values"): "hidden",
    (VISITOR, "comment"): "hidden",
    (PARTICIPANT, "score.values"): "hidden",
    (PARTICIPANT, "comment"): "hidden",
    (JUDGE, "member_emails"): "hidden",
    (JUDGE, "panel_totals"): "hidden",
    (ORGANIZER, "panel_totals"): "visible",
    (ADMIN, "panel_totals"): "visible",
}

BLIND_FIELDS = {"team_name", "team_id"}


def allows(roles: set[str], action: str, *, target_is_self: bool = False, published: bool = False) -> bool:
    roles = set(roles or {VISITOR})
    if action == "results.read" and published:
        return True
    if action == "scores.read_named":
        if roles & STAFF:
            return True
        return target_is_self and JUDGE in roles
    if action == "scores.read_own":
        return JUDGE in roles
    allowed = ACTION_POLICY.get(action, set())
    if action in {"gallery.read", "project.read", "about.read"}:
        return True
    return bool(roles & allowed)


def hidden_fields(roles: set[str], *, blind: bool) -> set[str]:
    hidden = set()
    for (role, field), visibility in FIELD_POLICY.items():
        if role in roles and visibility == "hidden":
            hidden.add(field)
    if blind and JUDGE in roles and not (roles & STAFF):
        hidden.update(BLIND_FIELDS)
    return hidden


def describe() -> list[dict]:
    """Plain-language rows for /about/access, generated from the tables above."""
    rows = []
    for action, roles in ACTION_POLICY.items():
        rows.append(
            {
                "action": action,
                "who": ", ".join(sorted(roles)),
                "note": _NOTES.get(action, ""),
            }
        )
    rows.append(
        {
            "action": "field.blind_team",
            "who": "judge, when the event has blind judging on",
            "note": "Team name and team id are omitted in HTML, JSON and CSV.",
        }
    )
    rows.append(
        {
            "action": "field.panel_totals",
            "who": "organizer, admin",
            "note": "Hidden from judges. A page that returned it only as JSON would fail the column check.",
        }
    )
    return rows


_NOTES = {
    "gallery.read": "Public. No login, no redirect.",
    "project.read": "Submitted projects are public. Drafts stay with the team, organizers and assigned judges.",
    "scores.read_own": "A judge reads their own rows. A participant is refused before 'me' is resolved.",
    "scores.read_named": "A judge may open only their own id. Anyone else who is not staff is refused before the id is loaded, so the answer is 403 rather than 404.",
    "scores.read_ledger": "The full ledger, including excluded duplicate rows.",
    "results.read": "Staff before publish. Everyone after publish.",
    "submission.create": "Refused with 409 once the event's close instant has passed. The body is not validated first.",
}
