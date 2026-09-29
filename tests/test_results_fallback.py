"""When the judge-bias model cannot be fitted, the ranking still follows the organizer's rubric weights.

A small event (two projects, two judges who agree) leaves no variation to estimate a judge's lean
from, so the REML grid has no finite likelihood and the results fall back to raw means. Those means
must be means of the weighted totals in scores.csv, and the page must say no adjustment was made.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import timedelta
from fractions import Fraction

import pytest
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import Event, Person, ResultsSnapshot, Track
from samepage.services.clock import db_now

pytestmark = [needs_db, pytest.mark.django_db]


def _two_by_two_event() -> tuple[Client, str, dict[str, str]]:
    admin = Client()
    admin.force_login(Person.objects.get(id="adm_01"))
    created = admin.post(
        "/e.json",
        {
            "name": "Weighted small",
            "submissions_close": (timezone.now() + timedelta(hours=1)).isoformat(),
            "tracks": ["Only"],
            "criteria": [{"label": "Impact", "weight": 9}, {"label": "Craft", "weight": 1}],
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    event_id = created.json()["id"]
    assert admin.post(f"/e/{event_id}/state.json", {"state": "open"}, content_type="application/json").status_code == 200
    track = Track.objects.get(event_id=event_id).id
    projects = {}
    for label in ("X", "Y"):
        member = Client()
        member.force_login(Person.objects.create_user(f"small.{label.lower()}@example.org", password="small password"))
        assert member.post(f"/e/{event_id}/teams.json", {"name": f"Team {label}"}, content_type="application/json").status_code == 201
        made = member.post(
            f"/e/{event_id}/projects.json", {"title": f"Project {label}", "track": track, "submit": True}, content_type="application/json"
        )
        assert made.status_code == 201, made.content
        projects[label] = made.json()["id"]
    judges = []
    for index in range(2):
        added = admin.post(
            f"/e/{event_id}/people.json", {"email": f"small.judge{index}@example.org", "role": "judge"}, content_type="application/json"
        ).json()
        browser = Client()
        assert browser.post("/" + added["password_link"].split("/", 3)[3], {"password": "small judge password"}).status_code == 303
        judges.append(browser)
    Event.objects.filter(id=event_id).update(submissions_close=db_now() - timedelta(seconds=1))
    for state in ("closed", "judging"):
        assert admin.post(f"/e/{event_id}/state.json", {"state": state}, content_type="application/json").status_code == 200
    issued = admin.post(f"/e/{event_id}/assignment-runs.json", {"kind": "initial", "coverage": 2}, content_type="application/json")
    assert issued.status_code == 201, issued.content
    # Both judges agree: X is 5 on Impact and 1 on Craft, Y is 3 and 5. Weighted 9:1 that is 4.6 and 3.2;
    # unweighted it would be 3.0 and 4.0, the other way round.
    marks = {projects["X"]: {"impact": 5, "craft": 1}, projects["Y"]: {"impact": 3, "craft": 5}}
    for browser in judges:
        rows = browser.get(f"/e/{event_id}/judge/batches.json").json()["items"]
        assert sorted(row["project_id"] for row in rows) == sorted(marks)
        for row in rows:
            done = browser.post(
                f"/e/{event_id}/judge/assignments/{row['project_id']}/finalize.json",
                {"criteria": marks[row["project_id"]]},
                content_type="application/json",
            )
            assert done.status_code == 200, done.content
    return admin, event_id, projects


def test_the_fallback_ranks_by_the_weighted_totals_of_the_ledger():
    admin, event_id, projects = _two_by_two_event()
    ledger = list(csv.DictReader(io.StringIO(admin.get(f"/e/{event_id}/scores.csv").content.decode("utf-8"))))
    totals = defaultdict(list)
    for row in ledger:
        assert row["counted"] == "true"
        totals[row["project_id"]].append(Fraction(row["weighted_total"]))
    assert totals[projects["X"]] == [Fraction(23, 5)] * 2 and totals[projects["Y"]] == [Fraction(16, 5)] * 2

    results = admin.get(f"/e/{event_id}/results.json").json()
    assert results["method"] == "raw_fallback" and results["degraded"] is True
    assert [row["id"] for row in results["items"]] == [projects["X"], projects["Y"]]
    for row in results["items"]:
        mean = sum(totals[row["id"]]) / len(totals[row["id"]])
        assert row["adjusted"] == row["raw_mean"] == f"{float(mean):.3f}"
    assert [row["adjusted"] for row in results["items"]] == ["4.600", "3.200"]
    # The page says what was done, not the model's story.
    assert "no judge adjustment" in results["story"] and "removing each judge" not in results["story"]
    assert "no variation is left to measure a judge's lean" in results["fallback_reason"]
    page = admin.get(f"/e/{event_id}/results").content.decode("utf-8")
    assert "no judge adjustment" in page and "removing each judge" not in page
    snapshot = ResultsSnapshot.objects.filter(event_id=event_id).order_by("-seq").first()
    assert snapshot.payload["reason"] == results["fallback_reason"]

    # Publishing freezes the same weighted order for everyone.
    assert admin.post(f"/e/{event_id}/publish.json").status_code == 200
    public = Client().get(f"/e/{event_id}/results.json").json()
    assert [row["id"] for row in public["items"]] == [projects["X"], projects["Y"]]
    assert [row["adjusted"] for row in public["items"]] == ["4.600", "3.200"]


def test_a_weight_change_moves_the_fallback_ranking():
    admin, event_id, projects = _two_by_two_event()
    assert [row["id"] for row in admin.get(f"/e/{event_id}/results.json").json()["items"]] == [projects["X"], projects["Y"]]
    # Craft now counts 9 times Impact: X is (5 + 9) / 10 = 1.4, Y is (3 + 45) / 10 = 4.8.
    changed = admin.post(
        f"/e/{event_id}/criteria.json",
        {"criteria": [{"key": "impact", "label": "Impact", "weight": 1}, {"key": "craft", "label": "Craft", "weight": 9}]},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.content
    results = admin.get(f"/e/{event_id}/results.json").json()
    assert results["method"] == "raw_fallback"
    assert [(row["id"], row["adjusted"]) for row in results["items"]] == [(projects["Y"], "4.800"), (projects["X"], "1.400")]


def test_the_fallback_uses_each_reviews_track_weights():
    from samepage.services.results import _fallback

    reviews = [
        {"project_id": "p1", "judge_id": "j1", "criteria": {"a": 5, "b": 1}, "weights": {"a": "1", "b": "1"}},
        {"project_id": "p2", "judge_id": "j1", "criteria": {"a": 1, "b": 4}, "weights": {"a": "1", "b": "3"}},
    ]
    meta = {"p1": {"title": "One"}, "p2": {"title": "Two"}}
    out = _fallback(reviews, meta, {"a": "1", "b": "1"}, "test")
    # p1 = 3.0 under the event weights; p2 = (1 + 12) / 4 = 3.25 under its track's 1:3.
    assert [(row["id"], row["adjusted_display"]) for row in out["rows"]] == [("p2", "3.250"), ("p1", "3.000")]
    assert out["rows"][0]["raw_mean_exact"] == "3.25"


def test_the_engine_refuses_to_fit_rounding_noise():
    from samepage.engine.snapshot import NotIdentifiable, build_snapshot

    weights = {"impact": "9", "craft": "1"}
    reviews = [
        {"project_id": project, "judge_id": judge, "criteria": criteria, "weights": weights}
        for judge in ("j1", "j2")
        for project, criteria in (("X", {"impact": 5, "craft": 1}), ("Y", {"impact": 3, "craft": 5}))
    ]
    with pytest.raises(NotIdentifiable):
        build_snapshot(reviews, {"X": {}, "Y": {}}, weights, judges_present=["j1", "j2"])
    # One disagreement is enough to fit.
    reviews[0] = {**reviews[0], "criteria": {"impact": 4, "craft": 1}}
    assert build_snapshot(reviews, {"X": {}, "Y": {}}, weights, with_draws=False, with_lojo=False)["method"] != "raw_fallback"
