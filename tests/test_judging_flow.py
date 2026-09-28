"""T2 over HTTP: assignment, the weighted rubric, scoring and finalizing, unlock, progress, the fixture's
awkward cases in the normalization, publish and its freeze, and the CSV exports.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import timedelta
from fractions import Fraction

import pytest
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import (
    Assignment,
    AuditEvent,
    Event,
    Person,
    ResultsSnapshot,
    RoleGrant,
    ScoreRev,
    Submission,
    Track,
)

pytestmark = [needs_db, pytest.mark.django_db]

SCORES = {"criteria": {"functionality": 5, "quality": 5, "innovation": 5}, "comment": "strong"}


def _rows(response) -> list[dict]:
    assert response.status_code == 200, response.content
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))


def _result(client, bearer, project_id: str) -> dict:
    items = client.get("/e/evt_01/results.json", **bearer("org")).json()["items"]
    return next(row for row in items if row["id"] == project_id)


# --- assignments -----------------------------------------------------------------------------


def test_the_demo_judges_have_open_work_on_a_fresh_seed(client, bearer):
    for slug, judge in (("jdg08", "jdg_08"), ("jdg03", "jdg_03")):
        batches = client.get("/e/evt_01/judge/batches.json", **bearer(slug)).json()
        open_rows = [row for row in batches["items"] if row["finalized"] == "false"]
        assert len(open_rows) == 2 and batches["open"] == 2
        for row in open_rows:
            assert client.get(f"/e/evt_01/judge/assignments/{row['project_id']}.json", **bearer(slug)).status_code == 200
    audit = AuditEvent.objects.get(event_id="evt_01", object_ref="run_demo")
    assert audit.after["demo"] is True


def test_manual_assignment_enforces_track_conflict_and_uniqueness(client, bearer):
    url = "/e/evt_01/assignments.json"
    # jdg_08 judges trk_04 only; prj_02 is in another track.
    other_track = Submission.objects.filter(event_id="evt_01").exclude(track_id="trk_04").exclude(state="withdrawn").first()
    response = client.post(url, {"judge": "jdg_08", "project": other_track.id}, content_type="application/json", **bearer("org"))
    assert response.status_code == 409 and "track" in response.json()["detail"]
    assert client.post(url, {"judge": "jdg_08", "project": "prj_01"}, content_type="application/json", **bearer("org")).status_code == 409
    assert client.post(url, {"judge": "per_priya1", "project": "prj_22"}, content_type="application/json", **bearer("org")).status_code == 422
    assert client.post(url, {"judge": "jdg_08", "project": "prj_07"}, content_type="application/json", **bearer("org")).status_code == 409
    # jdg_03 judges trk_04 and trk_05 and has not been assigned every project there.
    free = (
        Submission.objects.filter(event_id="evt_01", track_id__in=["trk_04", "trk_05"], state="submitted")
        .exclude(assignments__judge_id="jdg_03")
        .order_by("id")
        .first()
    )
    created = client.post(url, {"judge": "jdg_03", "project": free.id}, content_type="application/json", **bearer("org"))
    assert created.status_code == 201, created.content
    assert Assignment.objects.filter(judge_id="jdg_03", submission=free).exists()
    assert client.post(url, {"judge": "jdg_03", "project": free.id}, content_type="application/json", **bearer("org")).status_code == 409
    assert client.post(url, {"judge": "jdg_03", "project": free.id}, content_type="application/json", **bearer("jdg08")).status_code == 403
    listing = _rows(client.get("/e/evt_01/assignments.csv", **bearer("org")))
    assert any(row["judge_id"] == "jdg_03" and row["project_id"] == free.id and row["source"] == "manual" for row in listing)
    batches = client.get("/e/evt_01/judge/batches.json", **bearer("jdg03")).json()["items"]
    assert free.id in [row["project_id"] for row in batches]


def test_initial_issue_covers_every_project_and_a_second_run_adds_nothing(client, bearer):
    url = "/e/evt_01/assignment-runs.json"
    response = client.post(url, {"kind": "initial", "coverage": 4, "cap": 20}, content_type="application/json", **bearer("org"))
    assert response.status_code == 201, response.content
    run_id = response.json()["id"]
    report = client.get(f"/e/evt_01/assignment-runs/{run_id}.json", **bearer("org")).json()
    assert report["kind"] == "initial"
    issued = report["issued_pairs"]
    assert issued, "coverage 4 needs new assignments on the fixture"
    # Every issued pair respects the judge's tracks.
    from samepage.apps.portal.models import JudgeTrack

    for pair in issued:
        track = Submission.objects.get(id=pair["project_id"]).track_id
        assert JudgeTrack.objects.filter(person_id=pair["judge_id"], track_id=track).exists()
    assert report["report"]["coi_violations"] == 0
    again = client.post(url, {"kind": "initial", "coverage": 4, "cap": 20}, content_type="application/json", **bearer("org"))
    again_report = client.get(f"/e/evt_01/assignment-runs/{again.json()['id']}.json", **bearer("org")).json()
    assert again_report["issued_pairs"] == []
    assert AuditEvent.objects.filter(event_id="evt_01", action="assignment.initial").count() == 2


def test_topup_reassigns_an_abandoned_batch_and_is_deterministic(client, bearer):
    from samepage.services import judging

    batch = Assignment.objects.get(judge_id="jdg_08", submission_id="prj_15").batch
    assert client.post(f"/e/evt_01/batches/{batch.id}/abandon.json", **bearer("org")).status_code == 200
    run = judging.topup("evt_01", actor="org_01")
    pairs = [(row["project_id"], row["judge_id"]) for row in run.report["assignments"]]
    assert all(judge != "jdg_08" for _project, judge in pairs)
    # The same inputs and seed issue the same pairs (ids are sorted before the seeded shuffle).
    projects, judges, _ = judging._pools("evt_01")
    assert [row["id"] for row in projects] == sorted(row["id"] for row in projects)
    assert [row["id"] for row in judges] == sorted(row["id"] for row in judges)
    # Scoring an abandoned assignment is refused.
    response = client.post("/e/evt_01/judge/assignments/prj_15/scores.json", SCORES, content_type="application/json", **bearer("jdg08"))
    assert response.status_code == 409


# --- scoring: drafts do not count, finals do, results refit ----------------------------------


def test_a_draft_is_in_the_ledger_but_not_in_the_results(client, bearer):
    before = _result(client, bearer, "prj_15")
    progress = client.get("/e/evt_01/progress.json", **bearer("org")).json()["sentence"]
    saved = client.post("/e/evt_01/judge/assignments/prj_15/scores.json", SCORES, content_type="application/json", **bearer("jdg08"))
    assert saved.status_code == 201 and saved.json()["state"] == "draft"
    row = next(r for r in _rows(client.get("/e/evt_01/scores.csv", **bearer("org"))) if r["id"] == "jdg_08:prj_15")
    assert row["state"] == "draft" and row["counted"] == "false" and row["excluded_reason"] == "not_final:draft"
    after = client.get("/e/evt_01/progress.json", **bearer("org")).json()["sentence"]
    assert after["counted"] == progress["counted"] and after["excluded"] == progress["excluded"] + 1
    assert _result(client, bearer, "prj_15")["n_reviews"] == before["n_reviews"] == 2


def test_finalizing_counts_and_the_results_refit_on_the_next_read(client, bearer):
    snapshots = ResultsSnapshot.objects.filter(event_id="evt_01").count()
    before = _result(client, bearer, "prj_15")
    done = client.post("/e/evt_01/judge/assignments/prj_15/finalize.json", SCORES, content_type="application/json", **bearer("jdg08"))
    assert done.status_code == 200 and done.json()["state"] == "final"
    after = _result(client, bearer, "prj_15")
    assert after["n_reviews"] == 3 and float(after["raw_mean"]) > float(before["raw_mean"])
    assert ResultsSnapshot.objects.filter(event_id="evt_01").count() == snapshots + 1
    # A second read with nothing new does not refit.
    _result(client, bearer, "prj_15")
    assert ResultsSnapshot.objects.filter(event_id="evt_01").count() == snapshots + 1
    progress = client.get("/e/evt_01/progress.json", **bearer("org")).json()
    judge_row = next(row for row in progress["judges"] if row["judge_id"] == "jdg_08")
    assert judge_row["finalized"] >= 4 and judge_row["open"] == 1
    assert progress["recount"] == {"matched": 6, "total": 6}


def test_judges_score_only_their_own_assignments(client, bearer):
    # jdg_03 is not assigned prj_22; jdg_08 is.
    response = client.post("/e/evt_01/judge/assignments/prj_22/scores.json", SCORES, content_type="application/json", **bearer("jdg03"))
    assert response.status_code == 403
    assert client.post("/e/evt_01/judge/assignments/prj_22/scores.json", SCORES, content_type="application/json", **bearer("org")).status_code == 403
    assert client.get("/e/evt_01/judge/assignments/prj_22.json", **bearer("jdg03")).status_code == 403


def test_unlock_reopens_a_final_score_for_correction(client, bearer):
    assert client.post("/e/evt_01/judge/assignments/prj_15/finalize.json", SCORES, content_type="application/json", **bearer("jdg08")).status_code == 200
    changed = {"criteria": {"functionality": 2, "quality": 2, "innovation": 2}}
    assert client.post("/e/evt_01/judge/assignments/prj_15/finalize.json", changed, content_type="application/json", **bearer("jdg08")).status_code == 409
    assert client.post("/e/evt_01/assignments/jdg_08/prj_15/unlock.json", {"reason": "typo"}, content_type="application/json", **bearer("jdg08")).status_code == 403
    unlocked = client.post("/e/evt_01/assignments/jdg_08/prj_15/unlock.json", {"reason": "typo"}, content_type="application/json", **bearer("org"))
    assert unlocked.status_code == 200, unlocked.content
    row = next(r for r in _rows(client.get("/e/evt_01/scores.csv", **bearer("org"))) if r["id"] == "jdg_08:prj_15")
    assert row["counted"] == "false" and row["state"] == "unlocked"
    def status():
        rows = client.get("/e/evt_01/judge/batches.json", **bearer("jdg08")).json()["items"]
        return next(row["status"] for row in rows if row["project_id"] == "prj_15")

    assert status() == "to score"
    client.post("/e/evt_01/judge/assignments/prj_15/scores.json", changed, content_type="application/json", **bearer("jdg08"))
    assert status() == "draft saved"
    assert client.post("/e/evt_01/judge/assignments/prj_15/finalize.json", changed, content_type="application/json", **bearer("jdg08")).status_code == 200
    assert status() == "final"
    states = list(ScoreRev.objects.filter(judge_id="jdg_08", submission_id="prj_15", criterion="quality").order_by("rev").values_list("state", "value"))
    assert states == [("final", 5), ("unlocked", 5), ("draft", 2), ("final", 2)]
    assert AuditEvent.objects.filter(event_id="evt_01", action="score.unlock", object_ref="jdg_08:prj_15").exists()
    # Unlocking an imported fixture score works the same way; the chain stays intact.
    assert client.get("/e/evt_01/audit.json", **bearer("org")).json()["chain_ok"] == "true"


# --- the weighted rubric ---------------------------------------------------------------------


def test_organizer_weights_change_every_weighted_total_and_the_fit(client, bearer):
    before = _result(client, bearer, "prj_01")
    response = client.post(
        "/e/evt_01/criteria.json",
        {
            "criteria": [
                {"key": "functionality", "weight": 3},
                {"key": "quality", "weight": 1},
                {"key": "innovation", "weight": "0.5"},
            ],
            "tracks": {"trk_01": {"innovation": 4}},
        },
        content_type="application/json",
        **bearer("org"),
    )
    assert response.status_code == 200, response.content
    rows = _rows(client.get("/e/evt_01/scores.csv", **bearer("org")))
    for row in rows[:40]:
        weights = {"functionality": 3, "quality": 1, "innovation": Fraction(1, 2)}
        if row["track"] == "trk_01":
            weights["innovation"] = 4
        expected = sum(weights[key] * int(row[f"c_{key}"]) for key in weights) / sum(weights.values())
        # weighted_total is printed to 10 decimal places.
        assert abs(Fraction(row["weighted_total"]) - expected) < Fraction(1, 10**9)
    after = _result(client, bearer, "prj_01")
    assert after["raw_mean"] != before["raw_mean"]
    audit = AuditEvent.objects.filter(event_id="evt_01", action="rubric.update").last()
    assert audit.before["criteria"][0]["weight"] == "1" and audit.after["criteria"][0]["weight"] == "3"
    rubric = client.get("/e/evt_01/criteria.json").json()
    assert rubric["criteria"][2]["track_overrides"] == {"trk_01": "4"}


@pytest.mark.parametrize(
    "body, status",
    [
        ({"criteria": [{"key": "functionality", "weight": 1}]}, 409),
        ({"criteria": [{"key": "functionality", "weight": -1}, {"key": "quality", "weight": 1}, {"key": "innovation", "weight": 1}]}, 422),
        ({"criteria": [{"key": "functionality", "weight": "x"}, {"key": "quality", "weight": 1}, {"key": "innovation", "weight": 1}]}, 422),
        ({"tracks": {"trk_nope": {"quality": 2}}}, 422),
    ],
)
def test_bad_rubric_changes_are_refused(client, bearer, body, status):
    response = client.post("/e/evt_01/criteria.json", body, content_type="application/json", **bearer("org"))
    assert response.status_code == status, response.content


def test_the_rubric_form_posts_event_and_track_weights(client, django_user_model):
    browser = Client()
    browser.force_login(django_user_model.objects.get(id="org_01"))
    response = browser.post("/e/evt_01/criteria", {"weight_functionality": "2", "weight_quality": "1", "weight_innovation": "1", "weight_trk_02_quality": "5"})
    assert response.status_code == 303
    rubric = browser.get("/e/evt_01/criteria.json").json()["criteria"]
    assert rubric[0]["weight"] == "2" and rubric[1]["track_overrides"] == {"trk_02": "5"}
    assert browser.get("/e/evt_01/settings").status_code == 200


# --- judges: invite by email, set a password, score ------------------------------------------


def test_a_judge_invited_by_email_sets_a_password_and_scores(client, bearer):
    added = client.post(
        "/e/evt_02/people.json",
        {"email": "new.judge@example.org", "name": "New Judge", "role": "judge", "tracks": ["trk_e2"]},
        content_type="application/json",
        **bearer("org"),
    )
    assert added.status_code == 201, added.content
    link = added.json()["password_link"]
    assert "/password/pw_" in link
    judge = Person.objects.get(email="new.judge@example.org")
    assert not judge.has_usable_password()
    assert RoleGrant.objects.filter(person=judge, event_id="evt_02", role="judge").exists()
    path = link.split("localhost:8080", 1)[-1]
    browser = Client()
    assert browser.get(path).status_code == 200
    assert browser.post(path, {"password": "short"}).status_code == 422
    assert browser.post(path, {"password": "a judge password"}).status_code == 303
    assert browser.get("/account.json").json()["email"] == "new.judge@example.org"
    assert Client().post(path, {"password": "again a password"}).status_code == 404  # one use
    # A person who already has a password cannot be handed a reset link by an organizer.
    assert client.post(f"/e/evt_02/people/{judge.id}/password-link.json", **bearer("org")).status_code == 409
    people = _rows(client.get("/e/evt_02/people.csv", **bearer("org")))
    assert any(row["email"] == "new.judge@example.org" and row["tracks"] == "trk_e2" for row in people)
    assert client.get("/e/evt_02/people.json", **bearer("control")).status_code == 403


def test_an_organizer_cannot_take_over_an_account_from_another_event(client, bearer):
    # jdg_05 judges evt_01 and has never set a password. The evt_02 organizer invites them as a judge:
    # the account lives elsewhere, so it gets an acceptance link, no role yet, and no set-password link.
    added = client.post(
        "/e/evt_02/people.json", {"email": Person.objects.get(id="jdg_05").email, "role": "judge"}, content_type="application/json", **bearer("org")
    )
    assert added.status_code == 201
    body = added.json()
    assert body["password_link"] == "" and body["status"] == "invited" and "/accept/ra_" in body["accept_link"]
    assert not RoleGrant.objects.filter(person_id="jdg_05", event_id="evt_02").exists()
    # Not on evt_02, so there is nobody there to hand a password link for.
    assert client.post("/e/evt_02/people/jdg_05/password-link.json", **bearer("org")).status_code == 404
    assert client.post("/e/evt_01/people/adm_01/password-link.json", **bearer("org")).status_code == 409


def test_a_team_member_cannot_be_made_a_judge_of_the_same_event(client, bearer):
    response = client.post(
        "/e/evt_01/people.json", {"email": "priya1@example.org", "role": "judge"}, content_type="application/json", **bearer("org")
    )
    assert response.status_code == 409


# --- the fixture's awkward cases ---------------------------------------------------------------


def test_the_lab_lists_each_judges_lean_in_html_json_and_csv(client, bearer):
    lab = client.get("/e/evt_01/normalization.json", **bearer("org")).json()
    leans = {row["judge_id"]: row for row in lab["judge_leans"]}
    assert abs(leans["jdg_07"]["lean"] - 0.0665) < 1e-3 and "straight_line" in leans["jdg_07"]["flags"]
    # jdg_01 is on the event with no counted review: listed, with no lean to estimate.
    assert leans["jdg_01"]["n"] == 0 and leans["jdg_01"]["lean"] == ""
    rows = _rows(client.get("/e/evt_01/normalization/judges.csv", **bearer("org")))
    by_judge = {row["judge_id"]: row for row in rows}
    # A negative lean is a number in the CSV, not a formula-guarded text cell.
    assert float(by_judge["jdg_23"]["lean"]) < 0 and not by_judge["jdg_23"]["lean"].startswith("'")
    page = client.get("/e/evt_01/normalization", **bearer("org")).content.decode("utf-8")
    assert "Judge leans" in page and 'data-field="lean" value="0.06647' in page
    assert client.get("/e/evt_01/normalization/judges.json", **bearer("jdg08")).status_code == 403


def test_normalization_survives_zero_variance_and_one_review_judges(client, bearer):
    lab = client.get("/e/evt_01/normalization.json", **bearer("org")).json()
    assert lab["method"] == "reml"
    assert math.isfinite(float(lab["lambda"]))
    failures = {row["judge_id"]: row for row in lab["z_failures"]}
    assert failures["jdg_07"]["reason"] == "sd=0"  # gave 4/4/4 to everything
    assert failures["jdg_23"]["reason"] == "n<2"  # one review
    assert lab["flags"]["straight_line"] == ["jdg_07"]
    # jdg_01's only review is of the withdrawn Dry Harbour copy, so under keep-latest it counts for nothing.
    assert "jdg_01" in lab["flags"]["zero_counted"] and "jdg_23" in lab["flags"]["one_counted"]
    results = client.get("/e/evt_01/results.json", **bearer("org")).json()
    assert len(results["items"]) == 40  # 41 submissions, prj_07 withdrawn as a duplicate of prj_41
    assert "prj_07" not in [row["id"] for row in results["items"]]
    for row in results["items"]:
        assert math.isfinite(float(row["adjusted"])) and math.isfinite(float(row["raw_mean"]))
    assert sorted(row["rank"] for row in results["items"]) == list(range(1, 41))


def test_dry_harbour_is_an_explicit_audited_rule(client, bearer):
    group = client.get("/e/evt_01/duplicates/dup_01.json", **bearer("org")).json()
    assert [row["id"] for row in group["items"]] == ["prj_07", "prj_41"]
    assert group["status"] == "provisional" and group["resolution"] == "keep_latest"
    assert "same team" in group["rule"]
    applied = AuditEvent.objects.get(event_id="evt_01", action="duplicate.apply", object_ref="dup_01")
    assert applied.after["kept"] == "prj_41"
    kept_alone = next(row for row in client.get("/e/evt_01/results.json", **bearer("org")).json()["items"] if row["id"] == "prj_41")
    # Publishing waits for a person to confirm the rule.
    refused = client.post("/e/evt_01/publish.json", **bearer("org"))
    assert refused.status_code == 409 and "dup_01" in refused.json()["detail"]
    merged = client.post("/e/evt_01/duplicates/dup_01/confirm.json", {"resolution": "merge"}, content_type="application/json", **bearer("org"))
    assert merged.status_code == 200
    rows = _rows(client.get("/e/evt_01/scores.csv?project=prj_07", **bearer("org")))
    assert rows and all(row["counted"] == "true" and row["merged_into"] == "prj_41" for row in rows)
    results = {row["id"]: row for row in client.get("/e/evt_01/results.json", **bearer("org")).json()["items"]}
    assert "prj_07" not in results and results["prj_41"]["n_reviews"] == kept_alone["n_reviews"] + len(rows)
    lab = client.get("/e/evt_01/normalization.json", **bearer("org")).json()
    assert "jdg_01" in lab["flags"]["one_counted"]


# --- publish and the freeze -------------------------------------------------------------------


def test_publish_freezes_the_ranking_and_the_inputs(client, bearer):
    client.post("/e/evt_01/duplicates/dup_01/confirm.json", {"resolution": "keep_latest"}, content_type="application/json", **bearer("org"))
    assert client.get("/e/evt_01/results.json").status_code == 403  # not yet public
    published = client.post("/e/evt_01/publish.json", **bearer("org"))
    assert published.status_code == 200
    public = client.get("/e/evt_01/results.json").json()
    assert public["published"] is True and public["published_at"]
    sha = public["ranking_sha256"]
    refusals = [
        client.post("/e/evt_01/judge/assignments/prj_15/finalize.json", SCORES, content_type="application/json", **bearer("jdg08")),
        client.post("/e/evt_01/duplicates/dup_01/confirm.json", {"resolution": "merge"}, content_type="application/json", **bearer("org")),
        client.post("/e/evt_01/assignment-runs.json", {"kind": "topup"}, content_type="application/json", **bearer("org")),
        client.post("/e/evt_01/assignments.json", {"judge": "jdg_08", "project": "prj_29"}, content_type="application/json", **bearer("org")),
        client.post("/e/evt_01/criteria.json", {"criteria": [{"key": "functionality", "weight": 9}, {"key": "quality", "weight": 1}, {"key": "innovation", "weight": 1}]}, content_type="application/json", **bearer("org")),
        client.post("/e/evt_01/assignments/jdg_02/prj_01/unlock.json", {}, content_type="application/json", **bearer("org")),
    ]
    assert [response.status_code for response in refusals] == [409] * len(refusals)
    assert client.get("/e/evt_01/results.json").json()["ranking_sha256"] == sha
    csv_body = client.get("/e/evt_01/results.csv").content.decode("utf-8")
    assert csv_body.startswith("id,title,rank")
    publish_audit = AuditEvent.objects.get(event_id="evt_01", action="results.publish")
    assert publish_audit.after["ranking_sha256"] == sha


# --- exports and isolation for the new organizer routes ---------------------------------------


ORGANIZER_CSV = [
    "/e/evt_01/scores.csv",
    "/e/evt_01/projects.csv",
    "/e/evt_01/progress.csv",
    "/e/evt_01/results.csv",
    "/e/evt_01/assignments.csv",
    "/e/evt_01/assignment-runs.csv",
    "/e/evt_01/people.csv",
    "/e/evt_01/teams.csv",
    "/e/evt_01/criteria.csv",
    "/e/evt_01/audit.csv",
    "/e/evt_01/duplicates.csv",
    "/e/evt_01/normalization/ablation.csv",
]


@pytest.mark.parametrize("path", ORGANIZER_CSV)
def test_organizer_exports_every_stage_as_csv(client, bearer, path):
    response = client.get(path, **bearer("org"))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "null" not in response.content.decode("utf-8").split("\n", 1)[1]


@pytest.mark.parametrize(
    "path",
    [
        "/e/evt_01/assignments.json",
        "/e/evt_01/people.json",
        "/e/evt_01/teams.json",
        "/e/evt_01/settings.json",
    ],
)
@pytest.mark.parametrize("slug", ["jdg08", "priya1"])
def test_judges_and_participants_are_refused_the_organizer_views(client, bearer, path, slug):
    assert client.get(path, **bearer(slug)).status_code == 403
    assert client.get(path, HTTP_ACCEPT="application/json").status_code == 401


# --- the whole lifecycle on a new event --------------------------------------------------------


def test_full_lifecycle_create_submit_judge_publish(client, bearer):
    admin = Client()
    admin.force_login(Person.objects.get(id="adm_01"))
    event_id = admin.post(
        "/e.json",
        {"name": "Lifecycle", "submissions_close": (timezone.now() + timedelta(hours=1)).isoformat(), "tracks": ["Only"]},
        content_type="application/json",
    ).json()["id"]
    assert admin.post(f"/e/{event_id}/state.json", {"state": "open"}, content_type="application/json").status_code == 200
    track = Track.objects.get(event_id=event_id).id

    projects = []
    for index in range(3):
        member = Client()
        member.force_login(Person.objects.create_user(f"life{index}@example.org", password="life password"))
        member.post(f"/e/{event_id}/teams.json", {"name": f"Team {index}"}, content_type="application/json")
        created = member.post(
            f"/e/{event_id}/projects.json", {"title": f"Life {index}", "track": track, "submit": True}, content_type="application/json"
        )
        assert created.status_code == 201, created.content
        projects.append(created.json()["id"])

    judges = []
    for index in range(3):
        added = admin.post(
            f"/e/{event_id}/people.json", {"email": f"lj{index}@example.org", "role": "judge"}, content_type="application/json"
        ).json()
        judge_client = Client()
        path = added["password_link"].split("localhost:8080", 1)[-1]
        assert judge_client.post(path, {"password": "judge password"}).status_code == 303
        judges.append((added["person_id"], judge_client))

    # The deadline passes; the organizer closes the event, moves it to judging and issues batches.
    Event.objects.filter(id=event_id).update(submissions_close=timezone.now() - timedelta(seconds=1))
    assert admin.post(f"/e/{event_id}/state.json", {"state": "closed"}, content_type="application/json").status_code == 200
    assert admin.post(f"/e/{event_id}/state.json", {"state": "judging"}, content_type="application/json").status_code == 200
    issued = admin.post(f"/e/{event_id}/assignment-runs.json", {"kind": "initial", "coverage": 3}, content_type="application/json")
    assert issued.status_code == 201
    assert Assignment.objects.filter(submission__event_id=event_id).count() == 9

    for judge_index, (judge_id, judge_client) in enumerate(judges):
        batch = judge_client.get(f"/e/{event_id}/judge/batches.json").json()["items"]
        assert len(batch) == 3
        for row in batch:
            score = 1 + (judge_index + projects.index(row["project_id"])) % 5
            body = {"criteria": {"functionality": score, "quality": score, "innovation": 3}}
            done = judge_client.post(f"/e/{event_id}/judge/assignments/{row['project_id']}/finalize.json", body, content_type="application/json")
            assert done.status_code == 200, done.content
        assert judge_client.get(f"/e/{event_id}/judges/me/scores.csv").status_code == 200
        other = judges[(judge_index + 1) % 3][0]
        assert judge_client.get(f"/e/{event_id}/judges/{other}/scores.json").status_code == 403

    progress = admin.get(f"/e/{event_id}/progress.json").json()
    assert progress["sentence"]["counted"] == 9 and progress["sentence"]["fully_reviewed"] == 3
    assert all(row["open"] == 0 for row in progress["judges"])
    results = admin.get(f"/e/{event_id}/results.json").json()
    assert results["method"] in {"reml", "raw_fallback"} and len(results["items"]) == 3
    assert admin.post(f"/e/{event_id}/publish.json").status_code == 200
    public = Client().get(f"/e/{event_id}/results.json")
    assert public.status_code == 200 and len(public.json()["items"]) == 3
    assert Client().get(f"/e/{event_id}/results").status_code == 200
