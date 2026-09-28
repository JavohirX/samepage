"""Drive one whole event through a running portal over HTTP, the way people would. Stdlib only.

    SAMEPAGE_ADMIN_PASSWORD=... python tools/lifecycle_check.py --base http://localhost:8080 --admin-email ops@example.org

An admin signs in with a password and creates an event that closes in an hour. Three people sign
up, each starts a team (one invites a friend by link) and submits a project. The admin invites
three judges by email; each opens a one-time link and chooses a password. The admin then moves the
deadline to --close-in seconds from now, it passes, and edits are refused. The admin closes the event, issues batches, the judges score and
finalize, the admin publishes, and a stranger reads the frozen results. Every step checks the
status code it got; the first surprise exits 1. Nothing here uses a demo token or the seed, so it
works in production mode on an empty database (CI runs it there, see acceptance.yml).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

STEPS = 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Session:
    """Cookies by name, kept by hand (http.cookiejar is unreliable for a bare 'localhost')."""

    def __init__(self, base: str, name: str):
        self.base = base.rstrip("/")
        self.name = name
        self.cookies: dict[str, str] = {}

    def call(self, method: str, path: str, *, form=None, body=None):
        headers = {"Accept": "application/json" if body is not None else "text/html"}
        data = None
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self.cookies.items())
        if "csrftoken" in self.cookies:
            headers["X-CSRFToken"] = self.cookies["csrftoken"]
        if form is not None:
            form = dict(form)
            form.setdefault("csrfmiddlewaretoken", self.cookies.get("csrftoken", ""))
            data = urllib.parse.urlencode(form, doseq=True).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for _attempt in range(3):
            request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
            try:
                response = OPENER.open(request, timeout=60)
                status, header_list, raw = response.status, response.headers, response.read()
            except urllib.error.HTTPError as exc:
                status, header_list, raw = exc.code, exc.headers, exc.read()
            if status != 429:
                break
            # Sign-in, sign-up and set-password share a 10-a-minute throttle. Wait as told, then retry.
            wait = int(header_list.get("Retry-After") or 30)
            print(f"{self.name:>10} {method} {path} -> 429, waiting {wait} s as Retry-After says")
            time.sleep(wait)
        for value in header_list.get_all("Set-Cookie") or []:
            key, _, rest = value.partition("=")
            self.cookies[key.strip()] = rest.split(";", 1)[0]
        text = raw.decode("utf-8", "replace")
        return status, header_list, text

    def expect(self, method: str, path: str, status: int, *, form=None, body=None, what: str = ""):
        global STEPS
        got, headers, text = self.call(method, path, form=form, body=body)
        STEPS += 1
        line = f"{self.name:>10} {method} {path} -> {got}"
        if got != status:
            print(line + f"  EXPECTED {status}: {text[:400]}")
            sys.exit(1)
        print(line + (f"  {what}" if what else ""))
        if text and headers.get("Content-Type", "").startswith(("application/json", "application/problem+json")):
            return json.loads(text), headers
        return text, headers


def sign_up(base: str, name: str, email: str, password: str) -> Session:
    session = Session(base, name)
    session.expect("GET", "/signup", 200)
    session.expect("POST", "/signup", 303, form={"name": name, "email": email, "password": password})
    return session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8080")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--close-in", type=int, default=3, help="seconds from moving the deadline to it passing")
    args = parser.parse_args()
    password = os.environ.get("SAMEPAGE_ADMIN_PASSWORD")
    if not password:
        raise SystemExit("set SAMEPAGE_ADMIN_PASSWORD")
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    close = datetime.now(timezone.utc) + timedelta(hours=1)

    admin = Session(args.base, "admin")
    admin.expect("GET", "/login", 401, what="the sign-in form")
    admin.expect("POST", "/login", 303, form={"email": args.admin_email, "password": password})
    created, _ = admin.expect(
        "POST",
        "/e.json",
        201,
        body={
            "name": f"Lifecycle {stamp}",
            "submissions_close": close.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tracks": ["Main", "Second"],
            "prizes": ["Grand prize"],
            "criteria": [{"label": "Impact", "weight": 2}, {"label": "Craft", "weight": 1}],
            "max_team_size": 3,
        },
    )
    event = created["id"]
    admin.expect("POST", f"/e/{event}/state.json", 200, body={"state": "open"})
    detail, _ = admin.expect("GET", f"/e/{event}.json", 200)
    track = detail["tracks"][0]["id"]

    projects = []
    members = []
    for index in range(3):
        person = sign_up(args.base, f"team{index}", f"member{index}.{stamp}@example.org", f"member password {index}")
        team, _ = person.expect("POST", f"/e/{event}/teams.json", 201, body={"name": f"Team {index} {stamp}"})
        project, _ = person.expect(
            "POST", f"/e/{event}/projects.json", 201, body={"title": f"Project {index}", "track": track, "tech_tags": "python"}
        )
        person.expect("PATCH", f"/e/{event}/projects/{project['id']}.json", 200, body={"tagline": "edited before the deadline"})
        Session(args.base, "stranger").expect("GET", f"/e/{event}/projects/{project['id']}.json", 403, what="a draft is private")
        person.expect("POST", f"/e/{event}/projects/{project['id']}/submit.json", 200)
        projects.append(project["id"])
        members.append((person, team["id"], project["id"]))
    lead, team_id, _ = members[0]
    invite, _ = lead.expect("POST", f"/e/{event}/teams/{team_id}/invites.json", 201, body={"max_uses": 1})
    friend = sign_up(args.base, "friend", f"friend.{stamp}@example.org", "friend password")
    friend.expect("POST", invite["path"] + ".json", 200, what="joined by invite link")
    gallery, _ = Session(args.base, "visitor").expect("GET", f"/e/{event}/projects.json", 200)
    assert sorted(row["id"] for row in gallery["items"]) == sorted(projects), gallery

    judges = []
    for index in range(3):
        added, _ = admin.expect(
            "POST", f"/e/{event}/people.json", 201, body={"email": f"judge{index}.{stamp}@example.org", "role": "judge"}
        )
        path = "/" + added["password_link"].split("/", 3)[3]
        judge = Session(args.base, f"judge{index}")
        judge.expect("GET", path, 200)
        judge.expect("POST", path, 303, form={"password": f"judge password {index}"})
        judges.append((added["person_id"], judge))

    # The organizer moves the deadline to just ahead; then it passes.
    close = datetime.now(timezone.utc) + timedelta(seconds=args.close_in)
    admin.expect(
        "POST", f"/e/{event}/settings.json", 200, body={"submissions_close": close.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )
    wait = (close - datetime.now(timezone.utc)).total_seconds() + 1
    if wait > 0:
        print(f"waiting {wait:.0f} s for the deadline")
        time.sleep(wait)
    lead.expect("PATCH", f"/e/{event}/projects/{projects[0]}.json", 409, body={"title": "too late"}, what="deadline")
    admin.expect("POST", f"/e/{event}/state.json", 200, body={"state": "closed"})
    admin.expect("POST", f"/e/{event}/state.json", 200, body={"state": "judging"})
    admin.expect("POST", f"/e/{event}/assignment-runs.json", 201, body={"kind": "initial", "coverage": 3})

    for index, (judge_id, judge) in enumerate(judges):
        batch, _ = judge.expect("GET", f"/e/{event}/judge/batches.json", 200)
        for row in batch["items"]:
            value = 1 + (index + projects.index(row["project_id"])) % 5
            judge.expect(
                "POST",
                f"/e/{event}/judge/assignments/{row['project_id']}/scores.json",
                201,
                body={"criteria": {"impact": value, "craft": 3}, "comment": "draft"},
            )
            judge.expect(
                "POST",
                f"/e/{event}/judge/assignments/{row['project_id']}/finalize.json",
                200,
                body={"criteria": {"impact": value, "craft": 3}, "comment": "final"},
            )
        other = judges[(index + 1) % len(judges)][0]
        judge.expect("GET", f"/e/{event}/judges/{other}/scores.json", 403, what="peer scores refused")
        judge.expect("GET", f"/e/{event}/judges/me/scores.csv", 200)

    progress, _ = admin.expect("GET", f"/e/{event}/progress.json", 200)
    assert progress["sentence"]["counted"] == 9, progress["sentence"]
    admin.expect("GET", f"/e/{event}/scores.csv", 200)
    Session(args.base, "visitor").expect("GET", f"/e/{event}/results.json", 403, what="hidden before publish")
    admin.expect("POST", f"/e/{event}/publish.json", 200)
    public, _ = Session(args.base, "visitor").expect("GET", f"/e/{event}/results.json", 200)
    assert len(public["items"]) == 3, public
    judges[0][1].expect(
        "POST",
        f"/e/{event}/judge/assignments/{projects[0]}/finalize.json",
        409,
        body={"criteria": {"impact": 5, "craft": 5}},
        what="frozen after publish",
    )
    print(f"lifecycle PASS: {STEPS} requests, event {event}, ranking_sha256 {public['ranking_sha256']}")


if __name__ == "__main__":
    main()
