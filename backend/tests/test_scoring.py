"""The scoring service itself: the rules every path that records a result shares.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

import scoring
from model import (Attempt, Calibration, Contest, OverallRating, Problem, ProblemTag,
                   SeenProblem, TopicRating, db)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def a_rated_problem() -> Problem:
    return db.session.scalars(
        select(Problem).join(ProblemTag, ProblemTag.problem_id == Problem.id)
        .where(Problem.rating.between(1000, 1600)).limit(1)
    ).first()


def seed(user, rating=1500.0):
    db.session.add(OverallRating(user_id=user.id, rating=rating, rd=200.0,
                                 last_practised_at=NOW))
    db.session.add(Calibration(user_id=user.id, a=0.0, b=1.0, n_attempts=0))
    db.session.flush()


def open_attempt(user, problem, *, source="self_selected", session_id=None, slot=None):
    attempt = Attempt(user_id=user.id, problem_id=problem.id, source=source,
                      session_id=session_id, slot=slot, rated=True, started_at=NOW)
    db.session.add(attempt)
    db.session.flush()
    return attempt


def test_mark_seen_covers_the_twin_group_and_is_idempotent(app, user):
    """A Div. 1 problem and its Div. 2 copy must never be served as two problems."""
    db.session.add(Contest(id=999999, name="Twin Round", start_time=NOW))
    div2 = Problem(contest_id=999999, problem_index="A", name="Same", rating=1500,
                   twin_group=4242)
    div1 = Problem(contest_id=999999, problem_index="B", name="Same", rating=2000,
                   twin_group=4242)
    db.session.add_all([div2, div1])
    db.session.flush()

    scoring.mark_seen(user.id, div2, "attempted")
    scoring.mark_seen(user.id, div1, "attempted")  # the twin is already covered

    rows = db.session.query(SeenProblem).filter_by(user_id=user.id).all()
    assert {row.problem_id for row in rows} == {div1.id, div2.id}
    assert {row.reason for row in rows} == {"attempted"}


def test_rate_persists_the_overall_and_topic_rows(app, user):
    seed(user)
    problem = a_rated_problem()

    snapshot = scoring.rate(user.id, problem, 1, NOW)

    overall = db.session.get(OverallRating, user.id)
    assert overall.rating == snapshot.overall_after > 1500
    assert overall.last_practised_at == NOW
    assert 0.0 < snapshot.e_model < 1.0
    assert sum(snapshot.weights.values()) == pytest.approx(1.0)
    assert snapshot.effective_rating == 1500.0

    for tag_id in snapshot.weights:
        topic = db.session.get(TopicRating, (user.id, tag_id))
        assert topic is not None and topic.last_practised_at == NOW
        assert topic.rating_offset > 0


def test_score_attempt_applies_the_update_exactly_once(app, user):
    seed(user)
    problem = a_rated_problem()
    attempt = open_attempt(user, problem)
    before = db.session.get(OverallRating, user.id).rating

    first = scoring.score_attempt(attempt.id, 0, accepted_submission=None, now=NOW)
    rated_once = db.session.get(OverallRating, user.id).rating
    assert (first.s, first.overall_after) == (0, rated_once)
    assert rated_once < before

    # A repeated Give up, or a Done racing the timer, must not rate it twice --
    # and a solve on an already-scored attempt is not silently accepted.
    second = scoring.score_attempt(attempt.id, 1, accepted_submission=None,
                                   now=NOW + timedelta(minutes=1))
    assert (second.s, second.scored_at) == (0, first.scored_at)
    assert db.session.get(OverallRating, user.id).rating == rated_once
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 1


def test_score_attempt_rejects_a_solve_outside_the_window(app, user):
    seed(user)
    problem = a_rated_problem()
    attempt = open_attempt(user, problem)
    late = {"id": 9, "contestId": problem.contest_id,
            "problem": {"index": problem.problem_index}, "verdict": "OK",
            "creationTimeSeconds": int((NOW + timedelta(minutes=46)).timestamp())}

    with pytest.raises(scoring.ScoreRejected):
        scoring.score_attempt(attempt.id, 1, accepted_submission=late, now=NOW)
    assert db.session.get(Attempt, attempt.id).scored_at is None


def test_lock_attempt_refreshes_a_stale_copy(app, user):
    """The row lock must also reveal a change made by the request that won the race."""
    seed(user)
    problem = a_rated_problem()
    attempt = open_attempt(user, problem)
    attempt_id = attempt.id
    db.session.commit()

    stale = db.session.get(Attempt, attempt_id)  # now in the identity map
    db.session.execute(
        update(Attempt)
        .where(Attempt.id == attempt_id)
        .values(s=0, scored_at=NOW, e_model=0.5, problem_rating=problem.rating,
                overall_after=1400.0)
        .execution_options(synchronize_session=False)
    )
    assert stale.s is None  # our copy still says "open"

    locked = scoring.lock_attempt(attempt_id)
    assert locked is not None and (locked.s, locked.scored_at) == (0, NOW)


def test_touch_practised_ages_before_it_moves_the_stamp(app, user):
    """Finishing a session must not lose the days since the attempts were scored."""
    seed(user, rating=1500.0)
    db.session.add(TopicRating(user_id=user.id, tag_id=1, rating_offset=0.0, rd=100.0,
                               last_practised_at=NOW - timedelta(days=10)))
    db.session.flush()

    scoring.touch_practised(user.id, [1], NOW)

    topic = db.session.get(TopicRating, (user.id, 1))
    # sqrt(100^2 + 10^2 * 10) == sqrt(11000)
    assert topic.rd == pytest.approx(11000 ** 0.5)
    assert topic.last_practised_at == NOW


def test_score_attempt_accepts_a_solve_exactly_at_the_deadline(app, user):
    """The window is inclusive at 45 minutes; a second later is too late."""
    seed(user)
    problem = a_rated_problem()
    attempt = open_attempt(user, problem)
    on_time = {"id": 12, "contestId": problem.contest_id,
               "problem": {"index": problem.problem_index}, "verdict": "OK",
               "creationTimeSeconds": int((NOW + timedelta(minutes=45)).timestamp())}

    scored = scoring.score_attempt(attempt.id, 1, accepted_submission=on_time,
                                   now=NOW + timedelta(minutes=45))

    assert scored.s == 1
    assert scored.accepted_submission_id == 12
    assert scored.accepted_at == NOW + timedelta(minutes=45)
