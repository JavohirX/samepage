"""Conflict-of-interest violations are measured, not assumed to be zero."""

from samepage.engine.assign import assign, coi_violations

PROJECTS = [
    {"id": "p1", "track": "t", "team": "team_a", "team_emails": ["ana@example.org"]},
    {"id": "p2", "track": "t", "team": "team_b", "team_emails": ["bo@example.org"]},
]
JUDGES = [
    {"id": "j_ana", "tracks": ["t"], "email": "Ana@example.org", "coi_teams": []},
    {"id": "j_cy", "tracks": ["t"], "email": "cy@example.org", "coi_teams": ["team_b"]},
    {"id": "j_di", "tracks": ["t"], "email": "di@example.org", "coi_teams": []},
]


def test_membership_and_declared_conflicts_are_counted():
    found = coi_violations([("p1", "j_ana"), ("p2", "j_cy"), ("p1", "j_di")], PROJECTS, JUDGES)
    assert found == [
        {"project_id": "p1", "judge_id": "j_ana", "reason": "judge is on the team"},
        {"project_id": "p2", "judge_id": "j_cy", "reason": "declared conflict"},
    ]


def test_the_matcher_never_proposes_a_conflicted_pair():
    report = assign(PROJECTS, JUDGES, coverage=1, cap=2, seed=3)
    pairs = [(row["project_id"], row["judge_id"]) for row in report["assignments"]]
    assert pairs
    assert coi_violations(pairs, PROJECTS, JUDGES) == []
