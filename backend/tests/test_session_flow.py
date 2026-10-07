"""The session and attempt flow, through the real routes.

These are the user-visible invariants: a timer that runs out is scored before
anything else happens, Done needs Codeforces to confirm an in-window Accepted,
a failure is followed by another warm-up, an unopened pick survives a refresh,
and finishing queues exactly the revisits a failure earned.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import codeforces
import scoring
from conftest import auth
from model import (Attempt, Calibration, OverallRating, PracticeSession, Problem, Revisit,
                   SeenProblem, SessionPick, Tag, TopicRating, db)
from picking import TopicCandidate
from routes import session as session_routes

SESSIONS = "/api/sessions"
ATTEMPTS = "/api/attempts"


@pytest.fixture
def seeded(app, user, monkeypatch):
    """A seeded user whose topic draw is pinned to one tag."""
    tag = db.session.query(Tag).filter_by(name="dp").one()
    now = datetime.now(timezone.utc)
    db.session.add(OverallRating(user_id=user.id, rating=1500.0, rd=200.0,
                                 last_practised_at=now))
    db.session.add(Calibration(user_id=user.id, a=0.0, b=1.0, n_attempts=0))
    db.session.add(TopicRating(user_id=user.id, tag_id=tag.id, rating_offset=0.0,
                               rd=150.0, last_practised_at=now))
    db.session.flush()
    monkeypatch.setattr(session_routes, "_topic_candidates", lambda uid, overall, now: [
        TopicCandidate(tag_id=tag.id, tier_weight=1.0, emergence_rating=1000.0,
                       offset=0.0, rd=150.0, days_since_practised=None,
                       near_share=0.5, unseen_candidates=100),
    ])
    monkeypatch.setattr(session_routes, "_rng", random.Random(1234))
    return tag


def start(client, user):
    reply = client.post(SESSIONS, headers=auth(user.email))
    assert reply.status_code == 200, reply.data
    return reply.json


def next_pick(client, user, session_id):
    reply = client.post(f"{SESSIONS}/{session_id}/next", headers=auth(user.email))
    assert reply.status_code == 200, reply.data
    return reply.json


def open_pick(client, user, pick_id):
    reply = client.post(ATTEMPTS, headers=auth(user.email), json={"pick_id": pick_id})
    assert reply.status_code == 200, reply.data
    return reply.json


def expire(attempt_id):
    """Run the timer out (the route reads the row through the same session)."""
    attempt = db.session.get(Attempt, attempt_id)
    attempt.started_at = datetime.now(timezone.utc) - timedelta(minutes=50)
    db.session.flush()


def accepted_for(problem, *, verdict="OK", minutes_ago=0, submission_id=777):
    return {
        "id": submission_id,
        "contestId": problem["contest_id"],
        # +1s: the route's started_at has sub-second precision, and the API
        # reports whole seconds.
        "creationTimeSeconds": int(datetime.now(timezone.utc).timestamp()) + 1 - minutes_ago * 60,
        "verdict": verdict,
        "problem": {"contest_id": problem["contest_id"], "index": problem["index"]},
        "author": {"participantType": "PRACTICE"},
    }


def keys_in(payload) -> set[str]:
    if isinstance(payload, dict):
        return set(payload) | {key for value in payload.values() for key in keys_in(value)}
    if isinstance(payload, list):
        return {key for item in payload for key in keys_in(item)}
    return set()


def test_start_draws_the_topic_and_refuses_a_second_session(client, user, seeded):
    body = start(client, user)
    assert body["tag"] == "dp"
    assert body["next_slot"] == "warmup"
    assert body["picks"] == [] and body["attempts"] == []
    assert body["ended_at"] is None

    assert client.post(SESSIONS, headers=auth(user.email)).status_code == 409
    current = client.get(f"{SESSIONS}/current", headers=auth(user.email))
    assert current.status_code == 200 and current.json["id"] == body["id"]


def test_history_hides_the_editorial_until_the_attempt_is_scored(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    open_entry = client.get("/api/history", headers=auth(user.email)).json["attempts"][0]
    assert open_entry["s"] is None
    assert "editorial_search" not in keys_in(open_entry)

    client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email))
    scored_entry = client.get("/api/history", headers=auth(user.email)).json["attempts"][0]
    assert scored_entry["s"] == 0
    assert scored_entry["problem"]["editorial_search"].endswith("editorial")


def test_current_is_404_without_a_session(client, user, seeded):
    assert client.get(f"{SESSIONS}/current", headers=auth(user.email)).status_code == 404


def test_an_unopened_pick_survives_a_fresh_current_request(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    body = client.get(f"{SESSIONS}/current", headers=auth(user.email)).json
    assert [entry["id"] for entry in body["picks"]] == [pick["id"]]
    assert body["picks"][0]["problem"] == pick["problem"]
    assert body["attempts"] == []
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 0


def test_next_is_refused_while_a_pick_is_waiting(client, user, seeded):
    session = start(client, user)
    next_pick(client, user, session["id"])
    assert client.post(f"{SESSIONS}/{session['id']}/next",
                       headers=auth(user.email)).status_code == 409


def test_next_reports_the_pick_without_tags_or_editorial(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    assert pick["slot"] == "warmup"
    assert pick["target_probability"] == 0.80
    assert 0.0 < pick["p_cal"] < 1.0
    assert pick["problem"]["contest_id"] and pick["problem"]["index"]
    assert "tags" not in keys_in(pick)
    assert "editorial_search" not in keys_in(pick)


def test_next_can_be_told_which_slot_to_pick(client, user, seeded):
    session = start(client, user)
    reply = client.post(f"{SESSIONS}/{session['id']}/next", headers=auth(user.email),
                        json={"slot": "stretch"})
    assert reply.status_code == 200, reply.data
    assert reply.json["slot"] == "stretch"
    assert reply.json["target_probability"] == 0.25


def test_next_refuses_a_slot_that_is_not_one_of_the_three(client, user, seeded):
    session = start(client, user)
    reply = client.post(f"{SESSIONS}/{session['id']}/next", headers=auth(user.email),
                        json={"slot": "recall"})
    assert reply.status_code == 422


def test_give_up_scores_a_failure_and_asks_for_another_warmup(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    body = client.post(f"{ATTEMPTS}/{attempt['id']}/give-up",
                       headers=auth(user.email)).json
    assert body["s"] == 0
    assert body["overall_after"] < 1500

    # A failed warm-up earns another warm-up at the same target.
    again = next_pick(client, user, session["id"])
    assert (again["slot"], again["position"], again["target_probability"]) == ("warmup", 1, 0.80)
    assert again["problem"] != attempt["problem"]


def test_repeated_score_requests_do_not_rate_twice(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    first = client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email)).json
    overall = db.session.get(OverallRating, user.id).rating
    second = client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email)).json
    done = client.post(f"{ATTEMPTS}/{attempt['id']}/done", headers=auth(user.email)).json

    def result(payload):
        return {key: payload[key] for key in ("s", "scored_at", "overall_after")}
    assert result(second) == result(first) == result(done)
    assert db.session.get(OverallRating, user.id).rating == overall


def test_done_records_the_in_window_accepted_submission(client, user, seeded, monkeypatch):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    accepted = accepted_for(attempt["problem"], submission_id=555)
    monkeypatch.setattr(codeforces, "recent_submissions", lambda handle, **kw: [accepted])

    body = client.post(f"{ATTEMPTS}/{attempt['id']}/done", headers=auth(user.email)).json

    assert body["s"] == 1
    assert body["accepted_submission_id"] == 555
    assert body["accepted_at"] is not None
    assert body["overall_after"] > 1500
    assert body["problem"]["editorial_search"]  # offered only once it is over
    assert "tags" not in keys_in(body)

    # A solved warm-up promotes the session to main.
    assert next_pick(client, user, session["id"])["slot"] == "main"


def test_done_without_an_in_window_accept_keeps_the_attempt_open(client, user, seeded,
                                                                monkeypatch):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    monkeypatch.setattr(codeforces, "recent_submissions", lambda handle, **kw: [
        accepted_for(attempt["problem"], verdict="WRONG_ANSWER"),
        accepted_for(attempt["problem"], minutes_ago=50, submission_id=556),
    ])

    assert client.post(f"{ATTEMPTS}/{attempt['id']}/done",
                       headers=auth(user.email)).status_code == 409
    assert db.session.get(Attempt, attempt["id"]).scored_at is None

    body = client.get(f"{SESSIONS}/current", headers=auth(user.email)).json
    assert body["attempts"][0]["s"] is None
    assert "editorial_search" not in keys_in(body)  # no hint while it is open
    assert "tags" not in keys_in(body)


def test_done_on_an_expired_attempt_scores_without_calling_codeforces(client, user, seeded,
                                                                     monkeypatch):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    calls = []
    monkeypatch.setattr(codeforces, "recent_submissions",
                        lambda handle, **kw: calls.append(handle) or [])
    expire(attempt["id"])

    body = client.post(f"{ATTEMPTS}/{attempt['id']}/done", headers=auth(user.email)).json

    assert body["s"] == 0
    assert calls == []


def test_current_scores_an_expired_attempt_before_anything_else(client, user, seeded,
                                                                monkeypatch):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    monkeypatch.setattr(codeforces, "recent_submissions",
                        lambda handle, **kw: pytest.fail("no CF call on expiry"))
    expire(attempt["id"])

    body = client.get(f"{SESSIONS}/current", headers=auth(user.email)).json

    assert body["attempts"][0]["s"] == 0
    assert body["attempts"][0]["scored_at"] is not None


def test_replace_swaps_the_problem_keeps_the_target_and_records_a_skip(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    reply = client.post(f"{SESSIONS}/{session['id']}/slots/warmup/replace",
                        headers=auth(user.email))
    assert reply.status_code == 200, reply.data
    replacement = reply.json

    assert replacement["slot"] == "warmup"
    assert replacement["target_probability"] == pick["target_probability"]
    assert replacement["problem"] != pick["problem"]
    assert replacement["position"] > pick["position"]

    old = db.session.get(SessionPick, pick["id"])
    assert old.replaced_at is not None and old.opened_attempt_id is None
    # Unrated: a problem that was never opened is only remembered as skipped.
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 0
    assert db.session.query(SeenProblem).filter_by(
        user_id=user.id, reason="skipped").count() >= 1

    body = client.get(f"{SESSIONS}/current", headers=auth(user.email)).json
    assert [entry["id"] for entry in body["picks"]] == [replacement["id"]]


def test_replace_is_refused_when_no_pick_is_waiting(client, user, seeded):
    session = start(client, user)
    assert client.post(f"{SESSIONS}/{session['id']}/slots/warmup/replace",
                       headers=auth(user.email)).status_code == 409
    assert client.post(f"{SESSIONS}/{session['id']}/slots/nope/replace",
                       headers=auth(user.email)).status_code == 404


def test_cancelling_a_pick_goes_back_to_the_picker_without_a_trace(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    reply = client.post(f"{SESSIONS}/{session['id']}/picks/{pick['id']}/cancel",
                        headers=auth(user.email))
    assert reply.status_code == 200, reply.data
    assert reply.json["picks"] == []

    # Nothing was attempted and nothing was marked seen, so a cancel is not a skip.
    assert db.session.get(SessionPick, pick["id"]) is None
    assert db.session.query(SeenProblem).filter_by(user_id=user.id).count() == 0
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 0

    # The slot is free again, and a different one can be picked instead.
    chosen = client.post(f"{SESSIONS}/{session['id']}/next", headers=auth(user.email),
                         json={"slot": "stretch"})
    assert chosen.status_code == 200, chosen.data
    assert chosen.json["slot"] == "stretch"


def test_cancelling_is_refused_once_the_pick_is_opened(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])
    open_pick(client, user, pick["id"])

    reply = client.post(f"{SESSIONS}/{session['id']}/picks/{pick['id']}/cancel",
                        headers=auth(user.email))
    assert reply.status_code == 409
    assert client.post(f"{SESSIONS}/{session['id']}/picks/999999/cancel",
                       headers=auth(user.email)).status_code == 404


def test_finish_closes_the_session_and_queues_two_revisits_per_failure(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email))

    body = client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email)).json
    assert body["ended_at"] is not None
    assert body["attempts"][0]["s"] == 0
    assert client.get(f"{SESSIONS}/current", headers=auth(user.email)).status_code == 404

    revisits = db.session.query(Revisit).filter_by(source_attempt_id=attempt["id"]).all()
    today = datetime.now(timezone.utc).date()
    due = {revisit.kind: (revisit.due_on - today).days for revisit in revisits}
    assert set(due) == {"related", "recall"}
    assert due["recall"] == 7           # the repeat comes back in a week
    assert 14 <= due["related"] <= 28   # the transfer dose keeps its 2-4 weeks

    # Repeating the finish returns the same summary and queues nothing new.
    again = client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))
    assert again.status_code == 200 and again.json["ended_at"] == body["ended_at"]
    assert db.session.query(Revisit).filter_by(source_attempt_id=attempt["id"]).count() == 2


def test_finish_deletes_an_unopened_pick(client, user, seeded):
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))

    assert db.session.get(SessionPick, pick["id"]) is None
    assert db.session.query(Attempt).filter_by(user_id=user.id).count() == 0


def test_finish_drops_a_session_that_recorded_nothing(client, user, seeded):
    """An empty session is not history: finishing it removes it, picks and all."""
    session = start(client, user)
    pick = next_pick(client, user, session["id"])

    reply = client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))

    assert reply.status_code == 200
    assert reply.json["ended_at"] is not None
    assert reply.json["attempts"] == []
    assert reply.json["picks"] == []
    assert db.session.get(PracticeSession, session["id"]) is None
    assert db.session.get(SessionPick, pick["id"]) is None
    # The topic it drew is free again: a new session can be started at once.
    assert client.get(f"{SESSIONS}/current", headers=auth(user.email)).status_code == 404
    assert client.post(SESSIONS, headers=auth(user.email)).status_code == 200


def test_finish_refuses_while_an_attempt_is_running(client, user, seeded):
    session = start(client, user)
    open_pick(client, user, next_pick(client, user, session["id"])["id"])

    assert client.post(f"{SESSIONS}/{session['id']}/finish",
                       headers=auth(user.email)).status_code == 409


def test_patch_stores_the_key_idea_and_the_upsolve_flag(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    scored = client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email)).json

    body = client.patch(f"{ATTEMPTS}/{attempt['id']}", headers=auth(user.email),
                        json={"key_idea": "  the trick is parity  ", "upsolved": True}).json
    assert body["key_idea"] == "the trick is parity"
    assert body["upsolved_at"] is not None
    assert body["s"] == scored["s"] and body["overall_after"] == scored["overall_after"]

    cleared = client.patch(f"{ATTEMPTS}/{attempt['id']}", headers=auth(user.email),
                           json={"upsolved": False}).json
    assert cleared["upsolved_at"] is None and cleared["key_idea"] == "the trick is parity"


def test_patch_refuses_unknown_fields_and_unscored_attempts(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    assert client.patch(f"{ATTEMPTS}/{attempt['id']}", headers=auth(user.email),
                        json={"s": 1}).status_code == 400
    assert client.patch(f"{ATTEMPTS}/{attempt['id']}", headers=auth(user.email),
                        json={"key_idea": "too early"}).status_code == 409
    assert client.patch(f"{ATTEMPTS}/{attempt['id']}", headers=auth(user.email),
                        json={}).status_code == 400


def test_the_slot_sequence_runs_warmup_main_stretch_then_stops(client, user, seeded,
                                                              monkeypatch):
    session = start(client, user)
    slots = []
    for index in range(3):
        pick = next_pick(client, user, session["id"])
        slots.append(pick["slot"])
        attempt = open_pick(client, user, pick["id"])
        monkeypatch.setattr(codeforces, "recent_submissions", lambda handle, problem=attempt["problem"], **kw: [
            accepted_for(problem, submission_id=100 + index),
        ])
        scored = client.post(f"{ATTEMPTS}/{attempt['id']}/done", headers=auth(user.email)).json
        assert scored["s"] == 1

    assert slots == ["warmup", "main", "stretch"]
    assert client.post(f"{SESSIONS}/{session['id']}/next",
                       headers=auth(user.email)).status_code == 409


def test_a_second_session_is_blocked_by_an_open_attempt(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))

    assert client.post(SESSIONS, headers=auth(user.email)).status_code == 409
    assert db.session.get(Attempt, attempt["id"]).scored_at is None


def test_sessions_belong_to_their_user(client, user, seeded):
    session = start(client, user)
    assert client.get(f"{SESSIONS}/current",
                      headers=auth("intruder@example.com")).status_code == 404
    assert client.post(f"{SESSIONS}/{session['id']}/next",
                       headers=auth("intruder@example.com")).status_code == 404


def test_topic_candidates_count_the_catalogue_near_the_user(client, user, app):
    """The SQL behind the topic draw: near-level share and unseen candidates."""
    from model import ProblemTag
    from model.topic_rating import TOPIC_RD_CAP

    now = datetime.now(timezone.utc)
    tag = db.session.query(Tag).filter_by(name="dp").one()
    overall = 1500.0

    def dp_candidate():
        candidates = session_routes._topic_candidates(user.id, overall, now)
        return next(candidate for candidate in candidates if candidate.tag_id == tag.id)

    before = dp_candidate()
    assert before.near_share >= 0.03 and before.unseen_candidates >= 20
    assert before.rd == TOPIC_RD_CAP  # never practised: at the cap
    assert before.days_since_practised is None
    assert before.offset == 0.0

    # Marking one near-level problem seen must shrink that tag's candidate pool.
    problem = db.session.scalars(
        select(Problem).join(ProblemTag, ProblemTag.problem_id == Problem.id)
        .where(ProblemTag.tag_id == tag.id, Problem.rating.between(overall - 200, overall + 200))
    ).first()
    scoring.mark_seen(user.id, problem, "skipped")
    db.session.flush()

    assert dp_candidate().unseen_candidates < before.unseen_candidates


def test_a_real_topic_draw_starts_a_session(client, user, app):
    """No pinning: the draw runs against the synced catalog."""
    now = datetime.now(timezone.utc)
    db.session.add(OverallRating(user_id=user.id, rating=1500.0, rd=200.0,
                                 last_practised_at=now))
    db.session.flush()

    body = start(client, user)
    assert body["tag"]  # some eligible tag was drawn
    assert body["next_slot"] == "warmup"


def test_pause_freezes_the_timer_and_resume_banks_the_lost_time(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    paused = client.post(f"{ATTEMPTS}/{attempt['id']}/pause",
                         headers=auth(user.email)).json
    assert paused["paused_at"] is not None
    assert paused["deadline"] == attempt["deadline"]  # freezing must not move it

    # Paused at the very start, three hours ago: the original 45 minutes are
    # long gone, but a paused attempt never expires.
    now = datetime.now(timezone.utc)
    row = db.session.get(Attempt, attempt["id"])
    row.started_at = now - timedelta(hours=3)
    row.paused_at = now - timedelta(hours=3)
    db.session.flush()

    current = client.get(f"{SESSIONS}/current", headers=auth(user.email)).json
    assert current["attempts"][0]["scored_at"] is None

    resumed = client.post(f"{ATTEMPTS}/{attempt['id']}/resume",
                          headers=auth(user.email)).json
    assert resumed["paused_at"] is None
    # The three hours do not count: the deadline is back out at ~45 minutes.
    assert datetime.fromisoformat(resumed["deadline"]) > now + timedelta(minutes=40)
    assert db.session.get(Attempt, attempt["id"]).paused_seconds >= 3 * 3600 - 2


def test_pause_after_the_timer_ran_out_scores_the_attempt(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    expire(attempt["id"])

    reply = client.post(f"{ATTEMPTS}/{attempt['id']}/pause", headers=auth(user.email))
    assert reply.status_code == 409
    assert db.session.get(Attempt, attempt["id"]).scored_at is not None


def test_pause_and_resume_are_idempotent(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])

    first = client.post(f"{ATTEMPTS}/{attempt['id']}/pause", headers=auth(user.email)).json
    again = client.post(f"{ATTEMPTS}/{attempt['id']}/pause", headers=auth(user.email)).json
    assert again["paused_at"] == first["paused_at"]

    client.post(f"{ATTEMPTS}/{attempt['id']}/resume", headers=auth(user.email))
    banked = db.session.get(Attempt, attempt["id"]).paused_seconds
    client.post(f"{ATTEMPTS}/{attempt['id']}/resume", headers=auth(user.email))
    assert db.session.get(Attempt, attempt["id"]).paused_seconds == banked


def test_giving_up_a_paused_attempt_banks_the_pause_and_clears_it(client, user, seeded):
    session = start(client, user)
    attempt = open_pick(client, user, next_pick(client, user, session["id"])["id"])
    client.post(f"{ATTEMPTS}/{attempt['id']}/pause", headers=auth(user.email))

    now = datetime.now(timezone.utc)
    row = db.session.get(Attempt, attempt["id"])
    row.started_at = now - timedelta(minutes=10)
    row.paused_at = now - timedelta(minutes=10)
    db.session.flush()

    body = client.post(f"{ATTEMPTS}/{attempt['id']}/give-up",
                       headers=auth(user.email)).json
    assert body["s"] == 0 and body["paused_at"] is None
    assert db.session.get(Attempt, attempt["id"]).paused_seconds >= 10 * 60 - 2


# --- repeats: a failed problem keeps coming back until it is solved ----------

def fail_a_warmup(client, user):
    """One session, one failed warm-up, finished: the state that queues a recall."""
    session = start(client, user)
    pick = next_pick(client, user, session["id"])
    attempt = open_pick(client, user, pick["id"])
    client.post(f"{ATTEMPTS}/{attempt['id']}/give-up", headers=auth(user.email))
    client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))
    return pick, attempt


def make_due(source_attempt_id):
    """Move a recall's due date to today: the week has passed."""
    revisit = db.session.query(Revisit).filter_by(
        source_attempt_id=source_attempt_id, kind="recall").one()
    revisit.due_on = datetime.now(timezone.utc).date()
    db.session.flush()
    return revisit


def test_a_due_recall_serves_the_failed_problem_again_without_saying_so(client, user, seeded):
    pick, attempt = fail_a_warmup(client, user)
    make_due(attempt["id"])
    rating = db.session.get(OverallRating, user.id).rating
    calibration = db.session.get(Calibration, user.id).n_attempts

    session = start(client, user)
    repeat = next_pick(client, user, session["id"])

    # The same problem, in a payload indistinguishable from a normal warm-up.
    assert repeat["problem"] == pick["problem"]
    assert repeat["slot"] == "warmup"
    assert set(repeat) == set(pick)
    assert "recall" not in json.dumps(repeat)

    opened = open_pick(client, user, repeat["id"])
    assert opened["slot"] == "warmup"                 # still not a give-away
    assert db.session.get(Attempt, opened["id"]).slot == "recall"

    body = client.post(f"{ATTEMPTS}/{opened['id']}/give-up", headers=auth(user.email)).json

    assert body["s"] == 0
    assert body["slot"] == "recall"                   # honest once it is over
    assert body["rated"] is False
    # A repeat is not evidence: no rating update and no calibration refit.
    assert db.session.get(OverallRating, user.id).rating == rating
    assert db.session.get(Calibration, user.id).n_attempts == calibration

    # Failing it queues the next one, further out than the first.
    today = datetime.now(timezone.utc).date()
    following = db.session.query(Revisit).filter_by(
        source_attempt_id=opened["id"], kind="recall").one()
    assert (following.due_on - today).days == 21
    assert db.session.query(Revisit).filter_by(
        source_attempt_id=attempt["id"], kind="recall").one().status == "served"

    # A repeated score request hands back the same result without queuing again.
    again = client.post(f"{ATTEMPTS}/{opened['id']}/give-up", headers=auth(user.email)).json
    assert again["s"] == 0
    assert db.session.query(Revisit).filter_by(
        source_attempt_id=opened["id"], kind="recall").count() == 1


def test_solving_a_recall_first_try_ends_the_chain(client, user, seeded, monkeypatch):
    _, attempt = fail_a_warmup(client, user)
    make_due(attempt["id"])
    rating = db.session.get(OverallRating, user.id).rating

    session = start(client, user)
    repeat = next_pick(client, user, session["id"])
    opened = open_pick(client, user, repeat["id"])
    accepted = accepted_for(opened["problem"], submission_id=901)
    monkeypatch.setattr(codeforces, "recent_submissions", lambda handle, **kw: [accepted])

    body = client.post(f"{ATTEMPTS}/{opened['id']}/done", headers=auth(user.email)).json

    assert body["s"] == 1 and body["accepted_submission_id"] == 901
    assert db.session.get(Attempt, opened["id"]).rated is False
    assert db.session.get(OverallRating, user.id).rating == rating
    # Nothing is queued for a first-try solve: the problem is done with.
    assert db.session.query(Revisit).filter_by(
        user_id=user.id, kind="recall").count() == 1
    assert db.session.query(Revisit).filter_by(
        source_attempt_id=attempt["id"], kind="recall").one().status == "served"


def test_each_failed_recall_comes_back_further_out(client, user, seeded):
    _, attempt = fail_a_warmup(client, user)
    source = attempt["id"]

    for expected_gap in (21, 45):
        make_due(source)
        session = start(client, user)
        pick = next_pick(client, user, session["id"])
        opened = open_pick(client, user, pick["id"])
        client.post(f"{ATTEMPTS}/{opened['id']}/give-up", headers=auth(user.email))
        client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))

        following = db.session.query(Revisit).filter_by(
            source_attempt_id=opened["id"], kind="recall").one()
        today = datetime.now(timezone.utc).date()
        assert (following.due_on - today).days == expected_gap
        source = opened["id"]


def test_an_unopened_repeat_is_still_owed_after_the_session_ends(client, user, seeded):
    _, attempt = fail_a_warmup(client, user)
    make_due(attempt["id"])

    session = start(client, user)
    repeat = next_pick(client, user, session["id"])
    client.post(f"{SESSIONS}/{session['id']}/finish", headers=auth(user.email))

    # Never opened, so nothing was recorded -- and the repeat is still owed.
    assert db.session.get(SessionPick, repeat["id"]) is None
    assert db.session.query(Revisit).filter_by(
        source_attempt_id=attempt["id"], kind="recall").one().status == "pending"
