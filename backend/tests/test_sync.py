from datetime import datetime, timezone

import pytest

import codeforces
from conftest import auth
from model import (Attempt, Calibration, Contest, OverallRating, Problem, ProblemTag,
                   SeenProblem, Tag, db)
from routes import sync

CONTESTS = [
    {"id": 999001, "name": "Codeforces Round 999 (Div. 1)", "startTimeSeconds": 1_600_000_000},
    {"id": 999002, "name": "Codeforces Round 999 (Div. 2)", "startTimeSeconds": 1_600_100_000},
]
PROBLEMSET = {
    "problems": [
        # 999001A / 999002A share a name across consecutive contests: twins.
        {"contestId": 999001, "index": "A", "name": "Foo", "rating": 1000, "tags": ["dp"]},
        {"contestId": 999002, "index": "A", "name": "Foo", "rating": 1000, "tags": ["dp"]},
        {"contestId": 999001, "index": "B", "name": "Bar", "rating": 2000, "tags": ["fft"]},
        # Special problems are skipped entirely (no Problem, no "*special" tag).
        {"contestId": 999001, "index": "C", "name": "Apr", "rating": 1500,
         "tags": ["*special", "dp"]},
    ],
    "problemStatistics": [
        {"contestId": 999001, "index": "A", "solvedCount": 10},
        {"contestId": 999002, "index": "A", "solvedCount": 12},
        {"contestId": 999001, "index": "B", "solvedCount": 3},
    ],
}


def test_assign_twin_groups_links_same_name_in_consecutive_contests():
    groups = sync.assign_twin_groups([
        {"contestId": 100, "index": "A", "name": "Foo"},
        {"contestId": 100, "index": "B", "name": "Bar"},
        {"contestId": 101, "index": "A", "name": "Foo"},
        {"contestId": 101, "index": "C", "name": "Baz"},
    ])
    assert groups[(100, "A")] == groups[(101, "A")]
    assert (100, "B") not in groups
    assert (101, "C") not in groups


def test_emergence_ratings_takes_the_first_bucket_reaching_three_percent():
    samples = [(1000, ["widespread"])] * 99 + [(2000, ["niche"])] * 5
    out = sync.emergence_ratings(samples)
    assert out["widespread"] == 1000
    assert out["niche"] == 2000


def test_emergence_ratings_omits_tags_that_never_reach_three_percent():
    samples = [(1000, ["common"])] * 99 + [(1000, ["rare"])]
    assert "rare" not in sync.emergence_ratings(samples)


@pytest.mark.parametrize("headers", [{}, auth("bad")])
def test_sync_catalog_refuses_missing_or_bad_token(client, headers):
    assert client.post("/api/sync/catalog", headers=headers).status_code == 403


def test_sync_catalog_populates_problems_tags_and_emergence(client, user, monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "call",
                        lambda method, params=None, **kw: (
                            CONTESTS if method == "contest.list" else PROBLEMSET))

    assert client.post("/api/sync/catalog", headers=auth(user.email)).status_code == 200

    a1 = Problem.query.filter_by(contest_id=999001, problem_index="A").one()
    a2 = Problem.query.filter_by(contest_id=999002, problem_index="A").one()
    assert a1.twin_group is not None and a1.twin_group == a2.twin_group
    assert a1.solved_count == 10 and a2.solved_count == 12
    assert {t.name for t in a1.tags} == {"dp"}
    assert db.session.query(Tag).filter_by(name="dp").one().emergence_rating == 1000
    assert db.session.query(Tag).filter_by(name="fft").one().emergence_rating == 2000
    assert Problem.query.filter_by(contest_id=999001, problem_index="C").first() is None
    assert db.session.query(Tag).filter_by(name="*special").first() is None


# --- POST /sync/submissions and POST /sync/contests -------------------------

CONTEST_ID = 999888
START = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def submission(contest_id, index, verdict="OK", participant="PRACTICE", submission_id=1):
    return {
        "id": submission_id,
        "contestId": contest_id,
        "creationTimeSeconds": int(START.timestamp()) + 600,
        "verdict": verdict,
        "problem": {"contestId": contest_id, "index": index},
        "author": {"participantType": participant},
    }


def test_sync_submissions_sees_external_solves_without_rating_them(client, user, monkeypatch):
    solved = Problem.query.filter(Problem.rating.isnot(None)).limit(2).all()
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [
        submission(problem.contest_id, problem.problem_index, submission_id=index)
        for index, problem in enumerate(solved)
    ] + [
        submission(42424242, "Z", submission_id=9),          # not in the catalog
        submission(solved[0].contest_id, solved[0].problem_index,
                   verdict="WRONG_ANSWER", submission_id=10),
    ])

    body = client.post("/api/sync/submissions", headers=auth(user.email)).json

    assert body["fetched"] == 4
    assert body["accepted"] == 3
    assert body["mapped"] == 2  # the unknown contest is skipped
    assert body["newly_seen"] >= 2

    seen = db.session.query(SeenProblem).filter_by(user_id=user.id).all()
    assert {(row.problem_id, row.reason) for row in seen} >= {
        (problem.id, "external") for problem in solved
    }
    # Seen, never rated: no attempt, no rating, no calibration.
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 0
    assert db.session.get(OverallRating, user.id) is None
    assert db.session.get(Calibration, user.id) is None

    again = client.post("/api/sync/submissions", headers=auth(user.email)).json
    assert again["newly_seen"] == 0
    assert db.session.query(SeenProblem).filter_by(user_id=user.id).count() == len(seen)


@pytest.fixture
def contest_catalog(app):
    """One catalogued round with a cheap and an expensive problem."""
    db.session.add(Contest(id=CONTEST_ID, name="Codeforces Round 888 (Div. 2)",
                           division="Div. 2", start_time=START))
    tags = {name: db.session.query(Tag).filter_by(name=name).one()
            for name in ("dp", "greedy")}
    easy = Problem(contest_id=CONTEST_ID, problem_index="A", name="Easy", rating=1000)
    hard = Problem(contest_id=CONTEST_ID, problem_index="B", name="Hard", rating=2000)
    db.session.add_all([easy, hard])
    db.session.flush()
    db.session.add_all([
        ProblemTag(problem_id=easy.id, tag_id=tags["dp"].id),
        ProblemTag(problem_id=hard.id, tag_id=tags["greedy"].id),
    ])
    db.session.flush()
    return easy, hard


@pytest.fixture
def seeded_user(app, user):
    db.session.add(OverallRating(user_id=user.id, rating=1500.0, rd=200.0,
                                 last_practised_at=datetime.now(timezone.utc)))
    db.session.add(Calibration(user_id=user.id, a=0.0, b=1.0, n_attempts=0))
    db.session.flush()
    return user


def test_sync_contests_replays_solved_and_failed_then_skips_it(client, seeded_user,
                                                              contest_catalog, monkeypatch):
    easy, hard = contest_catalog
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: [{
        "contestId": CONTEST_ID, "contestName": "Codeforces Round 888 (Div. 2)", "rank": 500,
        "ratingUpdateTimeSeconds": int(START.timestamp()) + 7200,
        "oldRating": 1400, "newRating": 1500,
    }])
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [
        submission(CONTEST_ID, "A", participant="CONTESTANT", submission_id=11),
        submission(CONTEST_ID, "B", verdict="WRONG_ANSWER",
                   participant="CONTESTANT", submission_id=12),
        # Solved later in the practice room: not an in-contest solve.
        submission(CONTEST_ID, "B", submission_id=13),
    ])

    body = client.post("/api/sync/contests", headers=auth(seeded_user.email)).json

    assert (body["replayed"], body["problems"], body["solved"]) == (1, 2, 1)
    assert body["skipped"] == 0

    attempts = {
        attempt.problem_id: attempt
        for attempt in db.session.query(Attempt).filter_by(user_id=seeded_user.id)
    }
    assert set(attempts) == {easy.id, hard.id}
    assert (attempts[easy.id].s, attempts[hard.id].s) == (1, 0)
    assert all(attempt.source == "contest" and attempt.rated
               for attempt in attempts.values())
    rated = db.session.get(OverallRating, seeded_user.id).rating
    assert rated != 1500.0
    assert db.session.query(SeenProblem).filter_by(
        user_id=seeded_user.id, reason="contest").count() >= 2

    # A second sync has nothing new to replay and changes nothing.
    again = client.post("/api/sync/contests", headers=auth(seeded_user.email)).json
    assert (again["replayed"], again["already_recorded"]) == (0, 1)
    assert db.session.query(Attempt).filter_by(user_id=seeded_user.id).count() == 2
    assert db.session.get(OverallRating, seeded_user.id).rating == rated


def test_sync_contests_reports_an_entered_round_that_is_not_in_the_catalog(
        client, seeded_user, monkeypatch):
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: [])
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [
        submission(42424242, "A", participant="CONTESTANT"),
    ])

    body = client.post("/api/sync/contests", headers=auth(seeded_user.email)).json
    assert (body["replayed"], body["skipped"]) == (0, 1)
    assert db.session.query(Attempt).filter_by(user_id=seeded_user.id).count() == 0


def test_sync_routes_need_a_handle_and_a_seed(client, user, monkeypatch):
    fresh = client.post("/api/users/me/seed", headers=auth("newcomer-sync@example.com"))
    assert fresh.status_code == 400  # no handle yet
    assert client.post("/api/sync/submissions",
                       headers=auth("newcomer-sync@example.com")).status_code == 400

    # A handle but no seed: contests cannot be replayed, submissions still can.
    assert client.put("/api/users/me", headers=auth("newcomer-sync@example.com"),
                      json={"cf_handle": "some_handle"}).status_code == 200
    monkeypatch.setattr(codeforces, "PACING", 0)
    monkeypatch.setattr(codeforces, "user_rating", lambda handle: [])
    monkeypatch.setattr(codeforces, "user_status", lambda handle, **kw: [])
    assert client.post("/api/sync/contests",
                       headers=auth("newcomer-sync@example.com")).status_code == 409
    assert client.post("/api/sync/submissions",
                       headers=auth("newcomer-sync@example.com")).status_code == 200
