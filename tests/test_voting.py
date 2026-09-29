"""Tests for Package T3: Community voting, quadratic voting, balanced rotation, and tallies."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone

from conftest import needs_db
from samepage.apps.portal.models import Ballot, BallotLine, Event, MailOutbox, Person, Submission, Team, TeamMember, VotingConfig, VotingTally
from samepage.services import audit, voting
from samepage.services.clock import db_now

pytestmark = [needs_db, pytest.mark.django_db]


def _setup_event(event_id="evt_vote", submissions_close=None):
    now = db_now()
    if submissions_close is None:
        submissions_close = now - timedelta(hours=1)
    event = Event.objects.create(
        id=event_id,
        name="Voting Test Event",
        state="open",
        submissions_close=submissions_close,
    )
    # Create 3 active submissions
    for i in range(1, 4):
        team = Team.objects.create(id=f"tm_{event_id}_{i}", event=event, name=f"Team {i}")
        Submission.objects.create(
            id=f"prj_{event_id}_{i:02d}",
            event=event,
            team=team,
            track_id="trk_01",
            title=f"Project {i}",
            origin="import",
            submitted_at=submissions_close - timedelta(minutes=10),
            state="submitted",
        )
    return event


def test_voting_window_gating(client, bearer):
    event = _setup_event("evt_gate")
    org_headers = bearer("admin")

    # 1. Attempting to set window open earlier than submissions_close is refused (422)
    too_early = (event.submissions_close - timedelta(days=1)).isoformat()
    res = client.post(
        f"/e/{event.id}/voting/settings.json",
        {"opens_at": too_early, "credit_budget": 25},
        content_type="application/json",
        **org_headers,
    )
    assert res.status_code == 422
    assert "cannot open before submissions close" in str(res.json())

    # 2. Open voting legitimately
    res = client.post(
        f"/e/{event.id}/voting/settings.json",
        {
            "state": "open",
            "credit_budget": 25,
            "allow_accounts": True,
            "allow_open": True,
            "allow_email": True,
        },
        content_type="application/json",
        **org_headers,
    )
    assert res.status_code == 200
    assert res.json()["state"] == "open"


def test_quadratic_credit_budget_refusal(client, bearer):
    event = _setup_event("evt_budget")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_accounts=True)

    voter = Person.objects.create_user("voter.budget@example.org", password="pw")
    # Cast 30 credits (exceeds budget 25) -> 422
    votes_over = {f"prj_{event.id}_01": 20, f"prj_{event.id}_02": 10}
    res = client.post(
        f"/e/{event.id}/voting.json",
        {"votes": votes_over},
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {voter.tokens.create(kind='bearer', token_sha256='sha_b1').id}"},
    )
    # Use session sign-in for clean user principal
    c = Client()
    c.force_login(voter)
    res = c.post(
        f"/e/{event.id}/voting.json",
        {"votes": votes_over},
        content_type="application/json",
    )
    assert res.status_code == 422
    assert "exceeds credit budget" in str(res.json()).lower()

    # Cast 25 credits -> 200 OK
    votes_ok = {f"prj_{event.id}_01": 16, f"prj_{event.id}_02": 9}
    res = c.post(
        f"/e/{event.id}/voting.json",
        {"votes": votes_ok},
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["credits_spent"] == 25

    # Check database trigger directly refuses credit budget overflow on ballot_line
    ballot = Ballot.objects.get(id=res.json()["ballot_id"])
    with pytest.raises(Exception) as exc_info:
        with transaction.atomic():
            BallotLine.objects.create(
                ballot=ballot,
                submission_id=f"prj_{event.id}_03",
                credits=10,  # 25 + 10 = 35 > 25
            )
    assert "exceeds credit budget" in str(exc_info.value).lower()


def test_balanced_rotation(client):
    """S4: Balanced rotation (Latin-square rotation).

    Voter number i sees the list rotated by i, so every project appears in every position
    equally often across voters. Stable on reload.
    """
    from samepage.domain.voting import balanced_rotation

    items = ["P1", "P2", "P3", "P4"]
    # 4 voters: sequence numbers 0, 1, 2, 3
    orders = [balanced_rotation(items, i) for i in range(4)]
    assert orders[0] == ["P1", "P2", "P3", "P4"]
    assert orders[1] == ["P2", "P3", "P4", "P1"]
    assert orders[2] == ["P3", "P4", "P1", "P2"]
    assert orders[3] == ["P4", "P1", "P2", "P3"]

    # Check Latin square property: every item appears at index 0 exactly once
    pos_0 = [o[0] for o in orders]
    assert sorted(pos_0) == sorted(items)

    # Check stable across reloads for voter 2
    assert balanced_rotation(items, 2) == balanced_rotation(items, 2)


def test_hidden_results_before_close(client, bearer):
    """S5: Before close and count, nobody (including organizers) sees counts; only number of ballots."""
    event = _setup_event("evt_hidden")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_accounts=True)

    voter = Person.objects.create_user("voter.hidden@example.org", password="pw")
    c_voter = Client()
    c_voter.force_login(voter)
    c_voter.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_01": 9}},
        content_type="application/json",
    )

    # Anonymous / Participant reading tally before close -> 403
    res = Client().get(f"/e/{event.id}/voting/tally.json")
    assert res.status_code == 403
    res_voter = c_voter.get(f"/e/{event.id}/voting/tally.json")
    assert res_voter.status_code == 403

    # Organizer before close sees status 'in_progress' and ballot count only, NO project scores
    res_org = client.get(f"/e/{event.id}/voting/tally.json", **bearer("admin"))
    assert res_org.status_code == 200
    data = res_org.json()
    assert data["status"] == "in_progress"
    assert data["ballot_counts"]["total"] == 1
    assert "participants" not in data
    assert "public" not in data


def test_close_and_count_and_trigger_refusal(client, bearer):
    """S5: Explicit close and count creates immutable tally; Postgres trigger refuses later ballot writes."""
    event = _setup_event("evt_close")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_accounts=True)

    voter1 = Person.objects.create_user("voter.c1@example.org", password="pw")
    voter1.created_at = event.submissions_close - timedelta(days=2)
    voter1.save()
    c1 = Client()
    c1.force_login(voter1)
    c1.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_01": 16, f"prj_{event.id}_02": 9}},
        content_type="application/json",
    )

    # Organizer triggers close and count
    res_close = client.post(f"/e/{event.id}/voting/close.json", **bearer("admin"))
    assert res_close.status_code == 200
    tally = res_close.json()
    assert "combined" in tally
    assert tally["ballot_counts"]["counted"] == 1

    # Postgres trigger refuses any subsequent ballot write
    voter2 = Person.objects.create_user("voter.late@example.org", password="pw")
    c2 = Client()
    c2.force_login(voter2)
    res_late = c2.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_01": 4}},
        content_type="application/json",
    )
    assert res_late.status_code == 422
    assert "voting is closed" in str(res_late.json()).lower()

    # Public can now read tally
    res_tally = Client().get(f"/e/{event.id}/voting/tally.json")
    assert res_tally.status_code == 200
    assert res_tally.json()["ballot_counts"]["counted"] == 1


def test_sybil_and_burst_cutoff(client, bearer):
    """S3: Account-age cutoff = submission deadline. Later accounts' ballots kept, excluded, not counted."""
    event = _setup_event("evt_sybil")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_accounts=True)

    # Eligible account: created BEFORE submissions_close
    eligible = Person.objects.create_user("eligible@example.org", password="pw")
    eligible.created_at = event.submissions_close - timedelta(days=5)
    eligible.save()
    c_el = Client()
    c_el.force_login(eligible)
    res = c_el.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_01": 25}},
        content_type="application/json",
    )
    assert res.status_code == 200
    assert res.json()["excluded"] is False

    # Burst of 5 accounts created AFTER submissions_close
    for i in range(1, 6):
        late = Person.objects.create_user(f"burst_{i}@example.org", password="pw")
        late.created_at = event.submissions_close + timedelta(hours=i)
        late.save()
        c_late = Client()
        c_late.force_login(late)
        res = c_late.post(
            f"/e/{event.id}/voting.json",
            {"votes": {f"prj_{event.id}_02": 25}},
            content_type="application/json",
        )
        assert res.status_code == 200
        # Recorded, but marked excluded
        assert res.json()["excluded"] is True

    # Close and check counts
    res_close = client.post(f"/e/{event.id}/voting/close.json", **bearer("admin"))
    tally = res_close.json()
    assert tally["ballot_counts"]["total"] == 6
    assert tally["ballot_counts"]["counted"] == 1
    assert tally["ballot_counts"]["excluded"] == 5

    # Project 1 received sqrt(25) = 5.0000 influence
    # Project 2 received 0 counted influence (all votes were from excluded accounts)
    p1 = next(r for r in tally["combined"] if r["project_id"] == f"prj_{event.id}_01")
    p2 = next(r for r in tally["combined"] if r["project_id"] == f"prj_{event.id}_02")
    assert p1["influence"] == "5.0000"
    assert p2["influence"] == "0.0000"


def test_separate_tallies(client, bearer):
    """S3: Participants tally (team members in this event) and public tally shown side by side, never mixed."""
    event = _setup_event("evt_channels")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_accounts=True)

    # Participant on Team 1
    part_user = Person.objects.create_user("participant.user@example.org", password="pw")
    part_user.created_at = event.submissions_close - timedelta(days=1)
    part_user.save()
    team1 = Team.objects.get(id=f"tm_{event.id}_1")
    TeamMember.objects.create(event=event, team=team1, person=part_user)

    c_part = Client()
    c_part.force_login(part_user)
    c_part.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_02": 16}},
        content_type="application/json",
    )

    # Public user (not on any team in this event)
    pub_user = Person.objects.create_user("public.user@example.org", password="pw")
    pub_user.created_at = event.submissions_close - timedelta(days=1)
    pub_user.save()
    c_pub = Client()
    c_pub.force_login(pub_user)
    c_pub.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_03": 9}},
        content_type="application/json",
    )

    # Close and check channels
    res_close = client.post(f"/e/{event.id}/voting/close.json", **bearer("admin"))
    tally = res_close.json()

    # In participants tally: Project 2 has influence, Project 3 has 0
    p2_part = next(r for r in tally["participants"] if r["project_id"] == f"prj_{event.id}_02")
    p3_part = next(r for r in tally["participants"] if r["project_id"] == f"prj_{event.id}_03")
    assert p2_part["influence"] == "4.0000"
    assert p3_part["influence"] == "0.0000"

    # In public tally: Project 2 has 0, Project 3 has 3.0000
    p2_pub = next(r for r in tally["public"] if r["project_id"] == f"prj_{event.id}_02")
    p3_pub = next(r for r in tally["public"] if r["project_id"] == f"prj_{event.id}_03")
    assert p2_pub["influence"] == "0.0000"
    assert p3_pub["influence"] == "3.0000"


def test_email_magic_link_flow(client, bearer):
    """S1: One-time magic link waits in organizer outbox. Link is never shown on voter's screen."""
    event = _setup_event("evt_magic")
    voting.update_config(event, "admin", state="open", credit_budget=25, allow_email=True)

    # 1. Voter requests magic link
    c = Client()
    res = c.post(
        f"/e/{event.id}/voting/request-link.json",
        {"email": "voter.magic@example.org"},
        content_type="application/json",
    )
    assert res.status_code == 200
    # Link is NOT in response
    assert "token" not in res.json()
    assert "magic_url" not in res.json()

    # 2. Organizer visits outbox and finds link
    res_outbox = client.get(f"/e/{event.id}/outbox.json", **bearer("admin"))
    assert res_outbox.status_code == 200
    items = res_outbox.json()["items"]
    assert len(items) == 1
    assert items[0]["recipient_email"] == "voter.magic@example.org"
    magic_url = items[0]["magic_url"]
    token = magic_url.split("/")[-1]

    # 3. Voter clicks magic link -> redeems and redirects to voting page
    res_redeem = c.get(f"/vote/{token}")
    assert res_redeem.status_code == 303
    assert res_redeem.headers["Location"] == f"/e/{event.id}/voting"

    # Session is now authenticated for voting
    res_vote = c.post(
        f"/e/{event.id}/voting.json",
        {"votes": {f"prj_{event.id}_01": 9}},
        content_type="application/json",
    )
    assert res_vote.status_code == 200
    assert res_vote.json()["credits_spent"] == 9

    # Second redemption of same link fails (single use)
    res_second = Client().get(f"/vote/{token}")
    assert res_second.status_code == 422
