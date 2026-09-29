"""Shell context: demo mode, the signed-in person and, in demo mode, the demo accounts."""

from __future__ import annotations

from django.conf import settings

# The demo accounts in the order the sign-in screen and the demo strip list them, with the role
# each one signs in as and what is waiting for it on the seed. Demo mode only.
DEMO_ACCOUNTS = (
    ("admin", "Admin", "admin", "Creates events; every event's control panel"),
    ("org", "Organizer", "organizer", "Runs evt_01: progress, judges, results"),
    ("jdg08", "Judge A", "judge", "Two open reviews in the console"),
    ("jdg03", "Judge B", "judge", "Try Judge A's scores: refused with 403"),
    ("priya1", "Participant", "participant", "On a team in evt_01, which is closed"),
    ("control", "Participant (open event)", "participant", "evt_02 takes submissions"),
)


def demo_accounts():
    from samepage.domain.tokens import PRINCIPALS

    return [
        {"slug": slug, "label": label, "role": role, "note": note, "email": PRINCIPALS[slug]["email"]}
        for slug, label, role, note in DEMO_ACCOUNTS
        if slug in PRINCIPALS
    ]


def shell(request):
    user = getattr(request, "user", None)
    me = user if user is not None and getattr(user, "is_authenticated", False) else None
    context = {
        "demo_mode": settings.DEMO_MODE,
        "me": me,
        "public_url": settings.PUBLIC_URL,
    }
    if settings.DEMO_MODE:
        accounts = demo_accounts()
        context["demo_accounts"] = accounts
        context["me_slug"] = next((a["slug"] for a in accounts if me is not None and a["email"] == me.email), "")
    return context
