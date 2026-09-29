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
    "account.manage": EVERYONE,
    "event.create": {ADMIN},
    "event.manage": STAFF,
    "people.read": STAFF,
    "team.create": {VISITOR, PARTICIPANT},
    "team.read": {PARTICIPANT, ORGANIZER, ADMIN},
    "team.manage": {PARTICIPANT, ORGANIZER, ADMIN},
    "invite.accept": {VISITOR, PARTICIPANT},
    "role.accept": EVERYONE,
    "submission.create": {PARTICIPANT},
    "submission.update": {PARTICIPANT},
    "submission.withdraw": {PARTICIPANT, ORGANIZER, ADMIN},
    "scores.read_own": {JUDGE},
    "scores.read_named": JUDGES,
    "scores.read_ledger": STAFF,
    "score.unlock": STAFF,
    "progress.read": STAFF,
    "results.read": STAFF,
    "normalization.read": STAFF,
    "audit.read": STAFF,
    "duplicates.read": STAFF,
    "duplicates.resolve": STAFF,
    "assignment.read": STAFF,
    "assignment.run": STAFF,
    "judge.console": {JUDGE},
    "judge.score": {JUDGE},
    "publish": STAFF,
    "voting.read": EVERYONE,
    "voting.vote": EVERYONE,
    "voting.manage": STAFF,
    "voting.close": STAFF,
    "voting.tally": STAFF,
    "outbox.read": STAFF,
    "comment.create": EVERYONE,
    "comments.moderate": STAFF,
}

# These need a signed-in person even where the role column says visitor: a visitor who is
# signed in may start or join a team, an anonymous one is asked to sign in (401).
SIGNED_IN = {"account.manage", "team.create", "invite.accept", "role.accept", "comment.create"}

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


def allows(
    roles: set[str],
    action: str,
    *,
    target_is_self: bool = False,
    published: bool = False,
    signed_in: bool = True,
    voting_counted: bool = False,
) -> bool:
    roles = set(roles or {VISITOR})
    if action in SIGNED_IN and not signed_in:
        return False
    if action == "results.read" and published:
        return True
    if action == "voting.tally" and voting_counted:
        return True
    if action == "scores.read_named":
        if roles & STAFF:
            return True
        return target_is_self and JUDGE in roles
    if action == "scores.read_own":
        return JUDGE in roles
    allowed = ACTION_POLICY.get(action, set())
    if action in {"gallery.read", "project.read", "about.read", "voting.read", "voting.vote"}:
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
    "gallery.read": "Public. No login, no redirect. Drafts are not listed.",
    "project.read": "Submitted projects are public. A draft is visible to its team and to organizers only.",
    "account.manage": "Your own password. Signed in only.",
    "event.create": "Global admins create events and become the event's first organizer.",
    "event.manage": "Settings, dates, tracks, prizes, custom questions, rubric weights, state, judges and organizers.",
    "people.read": "Who holds which role on the event, with each judge's tracks and progress.",
    "team.create": "A signed-in person who is not a judge or organizer on the event, before the deadline.",
    "team.read": "The team page: members of that team and organizers. Other participants get 403.",
    "team.manage": "Invite links (create, revoke) for members of that team; removing a member is organizers only.",
    "invite.accept": "A signed-in person with the secret link joins the team. Judges and organizers of the event cannot.",
    "role.accept": "A judge or organizer role offered to an existing account is granted only when that account, signed in, opens the one-time link and accepts. Any other account is refused.",
    "scores.read_own": "A judge reads their own rows. A participant is refused before 'me' is resolved.",
    "scores.read_named": "A judge may open only their own id. Anyone else who is not staff is refused before the id is loaded, so the answer is 403 rather than 404.",
    "scores.read_ledger": "The full ledger, including excluded duplicate rows and drafts (counted=false).",
    "score.unlock": "An organizer reopens a finalized score. Audited; refused after publish.",
    "results.read": "Staff before publish. Everyone after publish, and then it is the frozen published snapshot.",
    "submission.create": "Team members only. Refused with 409 once the event's close instant has passed. The body is not validated first.",
    "submission.update": "Team members only, until the close instant (the service and a database trigger both refuse later edits).",
    "submission.withdraw": "Team members or organizers.",
    "judge.score": "Only on the judge's own assignments. Refused after publish.",
    "assignment.run": "Dry run, initial issue, top-up and one-by-one assignment. Refused after publish.",
}
