"""Write paths: wrong input is 4xx (never 500), a final score stays final, refusals roll back."""

from __future__ import annotations

import csv
import io
import logging

import pytest

from conftest import needs_db
from samepage.apps.portal.models import (
    Assignment,
    AssignmentRun,
    AuditEvent,
    Batch,
    Event,
    ScoreRev,
    Submission,
)

pytestmark = [needs_db, pytest.mark.django_db]


@pytest.fixture
def open_assignment():
    """One unscored assignment for Judge A (jdg_08), as a top-up would issue it."""
    run = AssignmentRun.objects.create(id="run_test", event_id="evt_01", kind="topup", seed=1)
    batch = Batch.objects.create(id="bat_test", event_id="evt_01", judge_id="jdg_08", run=run, state="issued")
    scored = set(ScoreRev.objects.filter(judge_id="jdg_08").values_list("submission_id", flat=True))
    project = (
        Submission.objects.filter(event_id="evt_01")
        .exclude(state="withdrawn")
        .exclude(id__in=scored)
        .order_by("id")
        .first()
    )
    Assignment.objects.create(batch=batch, judge_id="jdg_08", submission=project, source="topup")
    return project.id


def _signed_in(client, django_user_model, person_id):
    client.force_login(django_user_model.objects.get(id=person_id))
    return client


def test_finalize_form_post_saves_a_final_score(client, django_user_model, open_assignment):
    _signed_in(client, django_user_model, "jdg_08")
    url = f"/e/evt_01/judge/assignments/{open_assignment}/finalize"
    response = client.post(url, {"c_functionality": "4", "c_quality": "3", "c_innovation": "2", "comment": "ok"})
    assert response.status_code == 303
    states = set(ScoreRev.objects.filter(judge_id="jdg_08", submission_id=open_assignment).values_list("state", flat=True))
    assert states == {"final"}
    assert Assignment.objects.get(judge_id="jdg_08", submission_id=open_assignment).finalized_at is not None


def test_final_score_cannot_change_but_an_identical_repost_is_harmless(client, bearer, open_assignment):
    url = f"/e/evt_01/judge/assignments/{open_assignment}/finalize.json"
    body = {"criteria": {"functionality": 4, "quality": 4, "innovation": 4}}
    first = client.post(url, body, content_type="application/json", **bearer("jdg08"))
    assert first.status_code == 200
    again = client.post(url, body, content_type="application/json", **bearer("jdg08"))
    assert again.status_code == 200 and again.json()["saved"] is False
    changed = client.post(
        url, {"criteria": {"functionality": 1, "quality": 1, "innovation": 1}}, content_type="application/json", **bearer("jdg08")
    )
    assert changed.status_code == 409
    draft = client.post(
        f"/e/evt_01/judge/assignments/{open_assignment}/scores.json",
        {"criteria": {"functionality": 2, "quality": 2, "innovation": 2}},
        content_type="application/json",
        **bearer("jdg08"),
    )
    assert draft.status_code == 409


def test_imported_final_scores_refinalize_is_409_not_500(client, bearer):
    response = client.post(
        "/e/evt_01/judge/assignments/prj_01/finalize.json",
        {"criteria": {"functionality": 5, "quality": 5, "innovation": 5}},
        content_type="application/json",
        **bearer("jdg08"),
    )
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        [1, 2],
        {"criteria": [5, 5, 5]},
        {"criteria": {"functionality": "x", "quality": 5, "innovation": 5}},
        {"criteria": {"functionality": 9, "quality": 5, "innovation": 5}},
        # Booleans and fractions are refused, not coerced by int() to 1.
        {"criteria": {"functionality": True, "quality": 1, "innovation": 1}},
        {"criteria": {"functionality": 1.5, "quality": 1, "innovation": 1}},
        {"criteria": {"functionality": "1.5", "quality": 1, "innovation": 1}},
        {"criteria": {"functionality": 4.0, "quality": 4, "innovation": 4}},
        {"criteria": {"functionality": 3, "quality": 3, "innovation": 3}, "comment": ["not text"]},
    ],
)
def test_bad_score_bodies_are_422(client, bearer, open_assignment, body):
    response = client.post(
        f"/e/evt_01/judge/assignments/{open_assignment}/scores.json",
        body,
        content_type="application/json",
        **bearer("jdg08"),
    )
    assert response.status_code == 422
    assert not ScoreRev.objects.filter(judge_id="jdg_08", submission_id=open_assignment).exists()


def test_a_fraction_is_not_read_as_an_unchanged_draft(client, bearer, open_assignment):
    url = f"/e/evt_01/judge/assignments/{open_assignment}/scores.json"
    first = client.post(
        url, {"criteria": {"functionality": 1, "quality": 1, "innovation": 1}}, content_type="application/json", **bearer("jdg08")
    )
    assert first.status_code == 201
    # int(1.5) == 1, so this used to answer 200 "unchanged".
    response = client.post(
        url, {"criteria": {"functionality": 1.5, "quality": 1, "innovation": 1}}, content_type="application/json", **bearer("jdg08")
    )
    assert response.status_code == 422
    assert "functionality" in response.json()["detail"]


@pytest.mark.parametrize(
    "body, field",
    [
        ({"title": 123}, "title"),
        ({"title": "Cross", "track": "trk_01"}, "track"),
        ({"title": "Cross", "track": "nope"}, "track"),
        ({"title": "Cross", "tech_tags": "UPPER case"}, "tech_tags"),
        ({"title": ""}, "title"),
    ],
)
def test_bad_submissions_are_422_and_write_nothing(client, bearer, body, field):
    before = Submission.objects.filter(event_id="evt_02").count()
    response = client.post("/e/evt_02/projects.json", body, content_type="application/json", **bearer("control"))
    assert response.status_code == 422, response.content
    assert field in response.json()["detail"]
    assert Submission.objects.filter(event_id="evt_02").count() == before


def test_open_event_accepts_a_submission_on_its_own_track(client, bearer):
    response = client.post(
        "/e/evt_02/projects.json", {"title": "Control entry", "track": "trk_e2"}, content_type="application/json", **bearer("control")
    )
    assert response.status_code == 201
    created = Submission.objects.get(id=response.json()["id"])
    assert created.track_id == "trk_e2"
    second = client.post("/e/evt_02/projects.json", {"title": "Again"}, content_type="application/json", **bearer("control"))
    assert second.status_code == 409


def test_csv_neutralises_formulas_in_participant_text(client, bearer):
    client.post(
        "/e/evt_02/projects.json", {"title": "=HYPERLINK(\"http://x\")"}, content_type="application/json", **bearer("control")
    )
    body = client.get("/e/evt_02/projects.csv").content.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert rows[0]["title"].startswith("'=")


def test_blind_judging_drops_team_fields_for_judges_in_every_format(client, bearer):
    Event.objects.filter(id="evt_01").update(blind_judging=True)
    judge_json = client.get("/e/evt_01/projects.json", **bearer("jdg08")).json()
    assert "team_name" not in judge_json["columns"]
    assert all("team_name" not in item and "team_id" not in item for item in judge_json["items"])
    header = client.get("/e/evt_01/projects.csv", **bearer("jdg08")).content.decode("utf-8").splitlines()[0]
    assert "team_name" not in header
    assert b"NorthKiln" not in client.get("/e/evt_01/projects", **bearer("jdg08")).content
    staff = client.get("/e/evt_01/projects.json", **bearer("org")).json()
    assert "team_name" in staff["columns"]


def test_progress_numbers_are_checked_against_the_csv_they_link(client, bearer):
    progress = client.get("/e/evt_01/progress.json", **bearer("org")).json()
    assert progress["recount"] == {"matched": 6, "total": 6}
    for metric in progress["metrics"]:
        body = client.get(metric["href"], **bearer("org")).content.decode("utf-8")
        rows = list(csv.reader(io.StringIO(body)))[1:]
        assert len(rows) == metric["value"] == metric["csv_rows"], metric


def test_progress_recount_reports_a_number_that_disagrees_with_its_csv(client, bearer):
    # A withdrawal that is not a duplicate decision appears in projects.csv?state=withdrawn
    # but not in the "withdrawn duplicate" number, so the footer must say 5 of 6.
    Submission.objects.filter(id="prj_02").update(state="withdrawn", withdrawn_reason="team_left")
    progress = client.get("/e/evt_01/progress.json", **bearer("org")).json()
    assert progress["recount"] == {"matched": 5, "total": 6}
    mismatch = [m for m in progress["metrics"] if m["matches_csv"] == "false"]
    assert [m["key"] for m in mismatch] == ["withdrawn_duplicate"]
    page = client.get("/e/evt_01/progress", **bearer("org")).content.decode("utf-8")
    assert "5 of 6 numbers" in page


def test_merge_keeps_the_withdrawn_duplicate_count_honest(client, bearer):
    response = client.post(
        "/e/evt_01/duplicates/dup_01/confirm.json", {"resolution": "merge"}, content_type="application/json", **bearer("org")
    )
    assert response.status_code == 200
    progress = client.get("/e/evt_01/progress.json", **bearer("org")).json()
    assert progress["sentence"]["withdrawn_duplicate"] == 1
    assert progress["recount"] == {"matched": 6, "total": 6}


def test_illegal_transition_is_409(client, bearer):
    response = client.post("/e/evt_01/batches/bat_jdg_08/abandon.json", **bearer("org"))
    assert response.status_code == 409


def test_assignment_runs_are_audited_and_measure_conflicts(client, bearer):
    before = AuditEvent.objects.filter(event_id="evt_01").count()
    response = client.post(
        "/e/evt_01/assignment-runs.json", {"kind": "dry_run"}, content_type="application/json", **bearer("org")
    )
    assert response.status_code == 201
    run = AssignmentRun.objects.get(id=response.json()["id"])
    assert run.report["coi_violations"] == 0
    last = AuditEvent.objects.filter(event_id="evt_01").order_by("-seq").first()
    assert AuditEvent.objects.filter(event_id="evt_01").count() == before + 1
    assert (last.action, last.object_ref, last.actor) == ("assignment.dry_run", run.id, "org_01")
    bad = client.post("/e/evt_01/assignment-runs.json", {"kind": "nope"}, content_type="application/json", **bearer("org"))
    assert bad.status_code == 422


def test_dry_run_button_leads_to_a_page_that_renders(client, django_user_model):
    """The progress page's "Dry-run a fresh assignment" form, followed like a browser would."""
    _signed_in(client, django_user_model, "org_01")
    response = client.post("/e/evt_01/assignment-runs", {"kind": "dry_run"})
    assert response.status_code == 303
    page = client.get(response["Location"])
    assert page.status_code == 200, page.content[:400]
    run = AssignmentRun.objects.get(id=response["Location"].rsplit("/", 1)[-1])
    count = run.report["n_assignments"]
    assert count > 0
    assert f"<td>assignments</td><td>{count}</td>" in page.content.decode("utf-8")
    # A dry run issues nothing, so it lists no new assignments.
    assert "New assignments" not in page.content.decode("utf-8")


@pytest.mark.parametrize("suffix", ["", ".json", ".csv"])
def test_dry_run_page_renders_in_every_format(client, bearer, suffix):
    created = client.post(
        "/e/evt_01/assignment-runs.json", {"kind": "dry_run"}, content_type="application/json", **bearer("org")
    )
    response = client.get(f"/e/evt_01/assignment-runs/{created.json()['id']}{suffix}", **bearer("org"))
    assert response.status_code == 200


def test_a_dry_run_stored_with_a_bare_count_still_renders(client, bearer):
    # Dry runs written before n_assignments kept the count under "assignments".
    AssignmentRun.objects.create(
        id="run_oldshape", event_id="evt_01", kind="dry_run", seed=1, report={"assignments": 5, "coi_violations": 0}
    )
    response = client.get("/e/evt_01/assignment-runs/run_oldshape", **bearer("org"))
    assert response.status_code == 200
    assert "<td>assignments</td><td>5</td>" in response.content.decode("utf-8")


def test_topup_page_lists_the_pairs_it_issued(client, bearer):
    created = client.post("/e/evt_01/assignment-runs.json", {"kind": "topup"}, content_type="application/json", **bearer("org"))
    assert created.status_code == 201
    run = AssignmentRun.objects.get(id=created.json()["id"])
    page = client.get(f"/e/evt_01/assignment-runs/{run.id}", **bearer("org"))
    assert page.status_code == 200
    body = page.content.decode("utf-8")
    for row in run.report["assignments"]:
        assert f"{row['project_id']} → {row['judge_id']}" in body


def test_a_server_error_is_logged_with_the_reference_the_page_shows(client, bearer, monkeypatch, caplog):
    from samepage.services import ledger

    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(ledger, "progress_payload", boom)
    # The samepage logger writes to stdout and does not propagate; let caplog see it here.
    monkeypatch.setattr(logging.getLogger("samepage"), "propagate", True)
    with caplog.at_level(logging.ERROR, logger="samepage.errors"):
        response = client.get("/e/evt_01/progress.json", **bearer("org"))
    assert response.status_code == 500
    problem = response.json()
    assert problem["detail"] == "Something went wrong."
    assert "synthetic" not in response.content.decode("utf-8")
    assert any(problem["correlation_id"] in record.getMessage() for record in caplog.records)


def test_console_finalize_posts_the_fields_on_screen(client, django_user_model, open_assignment):
    _signed_in(client, django_user_model, "jdg_08")
    page = client.get(f"/e/evt_01/judge/assignments/{open_assignment}").content.decode("utf-8")
    assert f'formaction="/e/evt_01/judge/assignments/{open_assignment}/finalize"' in page
    # No second form with hidden copies of the scores taken when the page loaded.
    assert 'type="hidden" name="c_' not in page
