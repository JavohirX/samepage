"""The authorization matrix: every route, every demo principal, every format, over HTTP.

Each row is one URL on the seeded fixture and the status each principal gets, in this column
order: anonymous, participant (priya1, on tm_01 of evt_01), a participant of another event
(control, on evt_02), judge A (jdg_08), judge B (jdg_03), organizer (org_01), admin (adm_01).

Reads are checked in every format the route has, and a suffix the route does not have is 404
for everyone. Writes are sent as JSON with bearer tokens and an empty body, each in its own
rolled-back transaction: the policy check runs before the body is read, so a refused caller
gets 401 or 403 whatever it sends, and an allowed one reaches the service (409, 422 or 2xx).

`test_every_route_is_in_the_matrix` fails when a route is added to urls.py without a row here.
"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]

WHO = ("anon", "priya1", "control", "jdg08", "jdg03", "org", "admin")

PUBLIC = "200 200 200 200 200 200 200"
SIGNED_IN = "401 200 200 200 200 200 200"
STAFF = "401 403 403 403 403 200 200"
STAFF_POST_ONLY = "401 403 403 403 403 405 405"  # the policy passes, then GET is not a method
JUDGES_ONLY = "401 403 403 200 200 403 403"
ALL_404 = "404 404 404 404 404 404 404"

# path, formats (h = HTML, j = .json, c = .csv), expected GET status per principal.
READS = [
    ("/", "hjc", PUBLIC),
    ("/healthz", "hjc", PUBLIC),
    ("/readyz", "hjc", PUBLIC),
    ("/about/access", "hjc", PUBLIC),
    ("/e", "hjc", PUBLIC),
    ("/login", "h", "401 303 303 303 303 303 303"),  # the form, 401 for a stranger; signed in goes home
    ("/signup", "h", "200 303 303 303 303 303 303"),
    ("/account", "hj", SIGNED_IN),
    ("/e/new", "h", "401 403 403 403 403 403 200"),
    ("/demo/enter/org", "h", PUBLIC),  # a page with a POST button; demo mode only
    ("/password/pw_unknown", "h", ALL_404),
    ("/join/tj_unknown", "hj", ALL_404),
    ("/accept/ra_unknown", "hj", ALL_404),
    ("/e/evt_01", "hj", PUBLIC),
    ("/e/evt_01/settings", "hj", STAFF),
    ("/e/evt_01/state", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/criteria", "hjc", PUBLIC),
    ("/e/evt_01/people", "hjc", STAFF),
    ("/e/evt_01/people/per_priya1/password-link", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/teams", "hjc", STAFF),
    ("/e/evt_01/teams/tm_01", "hj", "401 200 403 403 403 200 200"),  # members and staff
    ("/e/evt_01/teams/tm_02", "hj", STAFF),  # priya1 is not on tm_02
    ("/e/evt_01/teams/tm_01/invites", "hj", "401 405 403 403 403 405 405"),
    ("/e/evt_01/teams/tm_01/invites/inv_x/revoke", "hj", "401 405 403 403 403 405 405"),
    ("/e/evt_01/teams/tm_01/leave", "hj", "401 405 403 403 403 405 405"),
    ("/e/evt_01/teams/tm_01/members/per_priya1/remove", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/projects", "hjc", PUBLIC),
    ("/e/evt_01/projects/new", "h", "401 200 403 403 403 403 403"),
    ("/e/evt_01/projects/prj_01", "hj", PUBLIC),
    ("/e/evt_01/projects/prj_01/edit", "h", "401 200 403 403 403 403 403"),
    ("/e/evt_01/projects/prj_01/submit", "hj", "401 405 403 403 403 403 403"),
    ("/e/evt_01/projects/prj_01/withdraw", "hj", "401 405 403 403 403 405 405"),
    ("/e/evt_01/projects/prj_01/media", "hj", "401 405 403 403 403 403 403"),
    ("/e/evt_01/projects/prj_01/media/1", "h", ALL_404),
    ("/e/evt_01/projects/prj_01/media/1/delete", "hj", "401 405 403 403 403 403 403"),
    ("/e/evt_01/scores", "hjc", STAFF),
    ("/e/evt_01/progress", "hjc", STAFF),
    ("/e/evt_01/results", "hjc", "403 403 403 403 403 200 200"),  # unpublished: 403 even anonymous
    ("/e/evt_01/publish", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/normalization", "hjc", STAFF),
    ("/e/evt_01/normalization/judges", "hjc", STAFF),
    ("/e/evt_01/duplicates", "hjc", STAFF),
    ("/e/evt_01/duplicates/dup_01", "hjc", STAFF),
    ("/e/evt_01/duplicates/dup_01/confirm", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/audit", "hjc", STAFF),
    ("/e/evt_01/assignments", "hjc", STAFF),
    ("/e/evt_01/assignments/jdg_08/prj_01/unlock", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/assignment-runs", "hjc", STAFF),
    ("/e/evt_01/assignment-runs/run_demo", "hjc", STAFF),
    ("/e/evt_01/batches/bat_demo_jdg_08/abandon", "hj", STAFF_POST_ONLY),
    ("/e/evt_01/judge/batches", "hjc", JUDGES_ONLY),
    ("/e/evt_01/judge/assignments/prj_01", "hj", JUDGES_ONLY),  # both demo judges reviewed prj_01
    ("/e/evt_01/judge/assignments/prj_22", "hj", "401 403 403 200 403 403 403"),  # only jdg_08's
    ("/e/evt_01/judge/assignments/prj_13", "hj", "401 403 403 403 200 403 403"),  # only jdg_03's
    ("/e/evt_01/judge/assignments/prj_01/scores", "hj", "401 403 403 405 405 403 403"),
    ("/e/evt_01/judge/assignments/prj_01/finalize", "hj", "401 403 403 405 405 403 403"),
    ("/e/evt_01/judges/me/scores", "hjc", JUDGES_ONLY),
    ("/e/evt_01/judges/jdg_08/scores", "hjc", "401 403 403 200 403 200 200"),
    ("/e/evt_01/judges/jdg_03/scores", "hjc", "401 403 403 403 200 200 200"),
    ("/e/evt_01/judges/jdg_99/scores", "hjc", "401 403 403 403 403 404 404"),  # 403 before the id is loaded
    # Another event: roles are per event. org_01 organizes both; the judges judge only evt_01.
    ("/e/evt_02/scores", "hjc", "401 403 403 403 403 200 200"),
    ("/e/evt_02/teams/tm_e2", "hj", "401 403 200 403 403 200 200"),
    ("/e/evt_02/judge/batches", "hjc", "401 403 403 403 403 403 403"),
    ("/e/evt_02/judges/me/scores", "hjc", "401 403 403 403 403 403 403"),
]

# method, path, expected status per principal for an empty JSON body.
WRITES = [
    ("POST", "/e.json", "401 403 403 403 403 403 422"),
    ("POST", "/account.json", "401 422 422 422 422 422 422"),
    ("POST", "/join/tj_unknown.json", ALL_404),
    ("POST", "/accept/ra_unknown.json", "401 404 404 404 404 404 404"),
    ("POST", "/e/evt_01/settings.json", "401 403 403 403 403 200 200"),
    ("PATCH", "/e/evt_01/settings.json", "401 403 403 403 403 200 200"),
    ("POST", "/e/evt_01/state.json", "401 403 403 403 403 422 422"),
    ("POST", "/e/evt_01/criteria.json", "401 403 403 403 403 200 200"),
    ("POST", "/e/evt_01/people.json", "401 403 403 403 403 422 422"),
    ("POST", "/e/evt_01/people/per_priya1/password-link.json", "401 403 403 403 403 409 409"),
    ("POST", "/e/evt_01/teams.json", "401 409 409 403 403 403 403"),  # evt_01 is closed
    ("POST", "/e/evt_01/teams/tm_01/invites.json", "401 409 403 403 403 403 403"),
    ("POST", "/e/evt_01/teams/tm_01/invites/inv_x/revoke.json", "401 404 403 403 403 404 404"),
    ("POST", "/e/evt_01/teams/tm_01/leave.json", "401 409 403 403 403 409 409"),
    ("POST", "/e/evt_01/teams/tm_01/members/per_priya1/remove.json", "401 403 403 403 403 409 409"),
    ("POST", "/e/evt_01/projects.json", "401 409 403 403 403 403 403"),  # run.py's closed-event 409
    ("POST", "/e/evt_01/projects/prj_01.json", "401 409 403 403 403 403 403"),
    ("PATCH", "/e/evt_01/projects/prj_01.json", "401 409 403 403 403 403 403"),
    ("POST", "/e/evt_01/projects/prj_01/submit.json", "401 409 403 403 403 403 403"),
    ("POST", "/e/evt_01/projects/prj_01/withdraw.json", "401 409 403 403 403 200 200"),
    ("POST", "/e/evt_01/projects/prj_01/media.json", "401 409 403 403 403 403 403"),
    ("POST", "/e/evt_01/projects/prj_01/media/1/delete.json", "401 409 403 403 403 403 403"),
    ("POST", "/e/evt_01/publish.json", "401 403 403 403 403 409 409"),  # dup_01 is still provisional
    ("POST", "/e/evt_01/duplicates/dup_01/confirm.json", "401 403 403 403 403 200 200"),
    ("POST", "/e/evt_01/assignments.json", "401 403 403 403 403 422 422"),
    ("POST", "/e/evt_01/assignments/jdg_08/prj_01/unlock.json", "401 403 403 403 403 200 200"),
    ("POST", "/e/evt_01/assignment-runs.json", "401 403 403 403 403 201 201"),  # a dry run by default
    ("POST", "/e/evt_01/batches/bat_demo_jdg_08/abandon.json", "401 403 403 403 403 200 200"),
    ("POST", "/e/evt_01/judge/assignments/prj_01/scores.json", "401 403 403 409 409 403 403"),  # final
    ("POST", "/e/evt_01/judge/assignments/prj_01/finalize.json", "401 403 403 422 422 403 403"),  # no scores sent
    ("POST", "/e/evt_01/judge/assignments/prj_22/scores.json", "401 403 403 422 403 403 403"),
    ("POST", "/e/evt_01/judge/assignments/prj_13/finalize.json", "401 403 403 403 422 403 403"),
    ("POST", "/e/evt_02/judge/assignments/prj_01/scores.json", "401 403 403 403 403 403 403"),
]

# Session routes: POST needs a CSRF token and starts or ends a cookie session (tests/test_sessions.py,
# tests/test_lifecycle.py). Their GETs are in READS.
SESSION_WRITES = {"login", "logout", "signup", "password/<slug:token>", "demo/enter/<slug:slug>"}


def _headers(bearer, who: str) -> dict:
    return {} if who == "anon" else bearer(who)


def _cases_for_reads():
    for path, formats, expected in READS:
        statuses = [int(value) for value in expected.split()]
        for suffix, letter in (("", "h"), (".json", "j"), (".csv", "c")):
            url = path + suffix  # "/.json" is the home page's JSON twin
            for who, status in zip(WHO, statuses):
                yield pytest.param(url, who, status if letter in formats else 404, id=f"{url}:{who}")


def _cases_for_writes():
    for method, path, expected in WRITES:
        for who, status in zip(WHO, (int(value) for value in expected.split())):
            yield pytest.param(method, path, who, status, id=f"{method} {path}:{who}")


@pytest.mark.parametrize("url, who, status", list(_cases_for_reads()))
def test_read(client, bearer, url, who, status):
    response = client.get(url, **_headers(bearer, who))
    assert response.status_code == status, (url, who, response.content[:300])
    if status in (401, 403) and url.endswith((".json", ".csv")):
        # An API refusal is a problem document, never a redirect or an HTML page.
        assert response["Content-Type"].startswith("application/problem+json")
        assert "Location" not in response
    if status in (401, 403):
        assert response["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize("method, path, who, status", list(_cases_for_writes()))
def test_write(client, bearer, method, path, who, status):
    send = getattr(client, method.lower())
    response = send(path, {}, content_type="application/json", **_headers(bearer, who))
    assert response.status_code == status, (method, path, who, response.content[:300])
    assert "Location" not in response or status in (200, 201)
    if status >= 400:
        assert response["Content-Type"].startswith("application/problem+json")


def _routes(patterns, prefix: str = ""):
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _routes(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern)


def _template(path: str) -> str:
    """'/e/evt_01/teams/tm_01' -> 'e/<slug:evt>/teams/<slug:team>', as urls.py spells it."""
    from django.urls import resolve

    match = resolve(path)
    return str(match.route)


def test_every_route_is_in_the_matrix():
    routes = {route for route in _routes(get_resolver().url_patterns) if not route.endswith(".<slug:fmt>")}
    assert len(routes) > 50, sorted(routes)
    covered = {_template(path) for path, _formats, _expected in READS}
    covered |= {_template(path.removesuffix(".json")) for _method, path, _expected in WRITES}
    covered |= SESSION_WRITES
    missing = sorted(routes - covered)
    assert not missing, f"routes with no row in the authorization matrix: {missing}"
