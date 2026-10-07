"""POST /api/users/me/seed.

The governing rule is that a recorded success implies a recorded failure, so
the central check is one entered contest whose solved problem and unsolved
problem both become rated attempts.
"""

from datetime import datetime, timezone

import pytest

import codeforces
from conftest import auth
from model import (Attempt, Calibration, Contest, OverallRating, Problem, ProblemTag,
                   SeenProblem, Tag, db)
from rating import NEWCOMER_BONUS

URL = "/api/users/me/seed"
CONTEST_ID = 999777
START = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

PROFILE = {"handle": "route_test_handle", "rating": 1500}
RATING_HISTORY = [{
    "contestId": CONTEST_ID, "contestName": "Codeforces Round 777 (Div. 2)", "rank": 900,
    "ratingUpdateTimeSeconds": int(START.timestamp()) + 7200,
    "oldRating": 1400, "newRating": 1500,
}]
SUBMISSIONS = [
    {"id": 555, "contestId": CONTEST_ID, "creationTimeSeconds": int(START.timestamp()) + 600,
     "verdict": "OK", "problem": {"contestId": CONTEST_ID, "index": "A"},
     "author": {"participantType": "CONTESTANT"}},
    {"id": 556, "contestId": CONTEST_ID, "creationTimeSeconds": int(START.timestamp()) + 900,
     "verdict": "WRONG_ANSWER", "problem": {"contestId": CONTEST_ID, "index": "B"},
     "author": {"participantType": "CONTESTANT"}},
]


@pytest.fixture
def codeforces_api(monkeypatch):
    """Point every Codeforces call at a tiny in-memory history."""
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_info", lambda handle: PROFILE)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: RATING_HISTORY)
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: SUBMISSIONS)


@pytest.fixture
def catalog(app):
    """One catalogued Div. 2 round with a cheap and an expensive problem."""
    db.session.add(Contest(id=CONTEST_ID, name="Codeforces Round 777 (Div. 2)",
                           division="Div. 2", start_time=START))
    tags = {
        name: db.session.query(Tag).filter_by(name=name).one()
        for name in ("dp", "greedy")
    }
    cheap = Problem(contest_id=CONTEST_ID, problem_index="A", name="Easy", rating=1000)
    hard = Problem(contest_id=CONTEST_ID, problem_index="B", name="Hard", rating=2000)
    db.session.add_all([cheap, hard])
    db.session.flush()
    db.session.add_all([
        ProblemTag(problem_id=cheap.id, tag_id=tags["dp"].id),
        ProblemTag(problem_id=hard.id, tag_id=tags["greedy"].id),
    ])
    db.session.flush()
    return cheap, hard


def test_seed_replays_solved_and_unsolved_problems_as_rated_attempts(
        client, user, catalog, codeforces_api):
    cheap, hard = catalog
    response = client.post(URL, headers=auth(user.email))

    assert response.status_code == 200
    body = response.json
    assert body["contests"] == {"replayed": 1, "skipped": 0}
    assert body["problems"] == {"replayed": 2, "skipped": 0, "solved": 1}

    # The initial rating is CF's 1500 plus the whole newcomer bonus after one
    # contest; replaying a failure on a 2000-rated problem must move it.
    assert body["rating"]["rating"] != 1500 + NEWCOMER_BONUS[1]
    assert body["rating"]["rating"] < 1500 + NEWCOMER_BONUS[1]
    assert 45 <= body["rating"]["rd"] <= 350

    attempts = {
        attempt.problem_id: attempt
        for attempt in db.session.query(Attempt).filter_by(user_id=user.id)
    }
    assert set(attempts) == {cheap.id, hard.id}
    assert all(a.rated and a.source == "contest" for a in attempts.values())

    solved, failed = attempts[cheap.id], attempts[hard.id]
    assert (solved.s, failed.s) == (1, 0)
    assert solved.accepted_submission_id == 555
    assert solved.accepted_at == datetime.fromtimestamp(
        int(START.timestamp()) + 600, tz=timezone.utc)
    assert failed.accepted_submission_id is None and failed.accepted_at is None
    # The cheap solve is replayed first (higher), the hard failure last.
    assert solved.overall_after > failed.overall_after
    assert failed.overall_after == pytest.approx(body["rating"]["rating"])
    assert all(a.e_model is not None and 0 < a.e_model < 1 for a in attempts.values())

    seen = {
        (row.problem_id, row.reason)
        for row in db.session.query(SeenProblem).filter_by(user_id=user.id)
    }
    assert seen == {(cheap.id, "contest"), (hard.id, "contest")}

    calibration = db.session.get(Calibration, user.id)
    assert (calibration.a, calibration.b, calibration.n_attempts) == (0.0, 1.0, 0)


def test_seed_is_idempotent_and_refuses_a_second_run(client, user, catalog, codeforces_api):
    first = client.post(URL, headers=auth(user.email))
    assert first.status_code == 200

    second = client.post(URL, headers=auth(user.email))
    assert second.status_code == 409
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 2


def test_seed_requires_a_handle(client):
    assert client.post(URL, headers=auth("no-handle@example.com")).status_code == 400


def test_seed_without_contests_uses_the_new_user_prior(client, user, monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_info", lambda handle: {"handle": handle})
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: [])
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [])

    body = client.post(URL, headers=auth(user.email)).json
    assert body["rating"] == {"rating": 800, "rd": 350}
    assert body["contests"] == {"replayed": 0, "skipped": 0}
    assert db.session.get(Calibration, user.id) is not None


def test_seed_refuses_when_the_catalog_cannot_map_the_history(client, user, monkeypatch):
    """A history we cannot map would be silently dropped, so it is a 409."""
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_info", lambda handle: PROFILE)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: [
        {"contestId": 42424242, "contestName": "Some Round", "rank": 1,
         "ratingUpdateTimeSeconds": 1_700_000_000, "oldRating": 1400, "newRating": 1500},
    ])
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [])

    assert client.post(URL, headers=auth(user.email)).status_code == 409
    assert db.session.get(OverallRating, user.id) is None


def test_seed_reports_unrated_problems_it_skipped(client, user, monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_info", lambda handle: PROFILE)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: RATING_HISTORY)
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: SUBMISSIONS[1:])

    db.session.add(Contest(id=CONTEST_ID, name="Codeforces Round 777 (Div. 2)",
                           division="Div. 2", start_time=START))
    db.session.add(Problem(contest_id=CONTEST_ID, problem_index="B", name="Hard",
                           rating=None))  # rating IS NULL: cannot be rated
    db.session.flush()

    body = client.post(URL, headers=auth(user.email)).json
    assert body["problems"] == {"replayed": 0, "skipped": 1, "solved": 0}
    assert db.session.query(SeenProblem).filter_by(user_id=user.id).count() == 1


def test_seed_maps_codeforces_failures_to_a_gateway_error(client, user, monkeypatch):
    def explode(handle):
        raise codeforces.CodeforcesError("Codeforces error: handle not found")
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_info", explode)

    response = client.post(URL, headers=auth(user.email))
    assert response.status_code == 502
    assert b"not found" in response.data
    assert db.session.get(OverallRating, user.id) is None
