"""The seven run.py checks, and the role x format matrix behind them, through Django's test client."""

from __future__ import annotations

import csv
import io

import pytest

from conftest import needs_db

pytestmark = [needs_db, pytest.mark.django_db]


def test_gallery_is_public_and_shows_the_fixture(client):
    response = client.get("/e/evt_01/projects")
    assert response.status_code == 200
    assert b"Glass Signal" in response.content
    assert response["Cache-Control"] == "public, max-age=30"


def test_closed_event_refuses_a_submission_before_validating_it(client, bearer):
    response = client.post(
        "/e/evt_01/projects.json", data={}, content_type="application/json", **bearer("priya1")
    )
    assert response.status_code == 409
    assert "submissions closed at 2026-03-01T18:00:00Z" in response.json()["detail"]


@pytest.mark.parametrize("suffix", ["", ".json", ".csv"])
def test_judge_reads_own_scores_in_every_format(client, bearer, suffix):
    response = client.get(f"/e/evt_01/judges/me/scores{suffix}", **bearer("jdg08"))
    assert response.status_code == 200


@pytest.mark.parametrize("suffix", ["", ".json", ".csv"])
@pytest.mark.parametrize("target", ["jdg_08", "jdg_99", "JDG_08"])
def test_judge_cannot_read_a_peer_in_any_format(client, bearer, suffix, target):
    response = client.get(f"/e/evt_01/judges/{target}/scores{suffix}", **bearer("jdg03"))
    assert response.status_code == 403
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/e/evt_01/judges/me/scores.json",
        "/e/evt_01/scores.csv",
        "/e/evt_01/progress.json",
        "/e/evt_01/results.json",
        "/e/evt_01/normalization.json",
        "/e/evt_01/audit.json",
        "/e/evt_01/duplicates.json",
        "/e/evt_01/assignment-runs.json",
        "/e/evt_01/judge/batches.json",
    ],
)
def test_participant_is_refused_everywhere_private(client, bearer, path):
    assert client.get(path, **bearer("priya1")).status_code == 403


@pytest.mark.parametrize("path", ["/e/evt_01/scores.csv", "/e/evt_01/progress.json", "/e/evt_01/audit.json"])
def test_anonymous_gets_401_problem_json_never_a_redirect(client, path):
    response = client.get(path, HTTP_ACCEPT="application/json")
    assert response.status_code == 401
    assert response["Content-Type"].startswith("application/problem+json")
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_organizer_csv_export_is_the_ledger(client, bearer):
    response = client.get("/e/evt_01/scores.csv", **bearer("org"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
    assert len(rows) == 126
    assert sum(row["counted"] == "true" for row in rows) == 121
    assert {row["excluded_reason"] for row in rows if row["counted"] == "false"} == {"withdrawn_duplicate:dup_01"}
    assert "null" not in response.content.decode("utf-8")


def test_an_invalid_bearer_never_falls_back_to_the_session(client, django_user_model):
    user = django_user_model.objects.get(id="org_01")
    client.force_login(user)
    response = client.get("/e/evt_01/scores.json", HTTP_AUTHORIZATION="Bearer nope")
    assert response.status_code == 401


def test_unknown_event_gallery_is_404(client):
    assert client.get("/e/evt_99/projects.json").status_code == 404


def test_projects_csv_is_not_cut_at_one_page(client, bearer):
    response = client.get("/e/evt_01/projects.csv?state=all", **bearer("org"))
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
    assert len(rows) == 41
