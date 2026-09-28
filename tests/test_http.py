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


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_an_unknown_api_url_is_problem_json_not_an_html_page(client, suffix):
    response = client.get(f"/no/such/thing{suffix}")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.json()["status"] == 404


def test_an_unknown_page_url_is_still_an_html_page(client):
    response = client.get("/no/such/thing")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")


@pytest.mark.parametrize("path, kind", [("/e/evt_01/progress.json", "application/problem+json"), ("/e/evt_01/progress", "text/html")])
def test_a_failure_outside_the_view_keeps_the_url_format(rf, path, kind):
    # handler500 runs when the error escapes DRF, e.g. Postgres is down before the view starts.
    from samepage.core.errors import handle_500

    response = handle_500(rf.get(path))
    assert response.status_code == 500
    assert response["Content-Type"].startswith(kind)


class _DatabaseDown:
    def cursor(self):
        from django.db import OperationalError

        raise OperationalError("connection refused")


@pytest.mark.parametrize("path", ["/readyz", "/readyz.json"])
def test_readyz_is_503_problem_json_when_the_database_is_down(client, monkeypatch, path):
    from samepage.apps.portal import views

    monkeypatch.setattr(views, "connection", _DatabaseDown())
    response = client.get(path)
    assert response.status_code == 503
    assert response["Content-Type"].startswith("application/problem+json")
    assert response.json()["detail"] == "The database is not reachable."
    assert client.get("/healthz").status_code == 200


def test_health_and_readiness_run_outside_the_request_transaction():
    # Opening the ATOMIC_REQUESTS transaction is what fails first when Postgres is down:
    # /healthz would be a 500 and /readyz a 500 instead of its 503.
    from django.urls import resolve

    for path in ("/healthz", "/healthz.json", "/readyz", "/readyz.json"):
        assert "default" in getattr(resolve(path).func, "_non_atomic_requests", set())
    assert "default" not in getattr(resolve("/e/evt_01/progress.json").func, "_non_atomic_requests", set())
