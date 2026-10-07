"""Attempt lifecycle: open a problem, finish it, give up, pause, annotate it.

A row exists only once the timer starts, so opening is the moment the pick
becomes history. Everything that records a result goes through
`scoring.score_attempt`, which is also the one place that enforces the
45-minute window and the once-only rating update. Pausing and resuming only
move `paused_at` / `paused_seconds`; they never touch a score.
"""

from __future__ import annotations

from datetime import datetime, timezone

import codeforces
import scoring
from flask import Blueprint, abort, g, request
from sqlalchemy import select

from model import Attempt, PracticeSession, Problem, SessionPick, db
from routes.views import attempt_json, scored_json

attempt_bp = Blueprint("attempts", __name__)

ANNOTATION_FIELDS = ("key_idea", "upsolved")


@attempt_bp.post("")
def open_attempt():
    """Open the session's picked problem and start its 45-minute timer.

    A pick is the only way in: a problem done on your own time is not a training
    attempt at all, and the submissions sync already marks it seen.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or set(body) != {"pick_id"}:
        abort(400, "send the pick_id of the pick to open")
    if not isinstance(body["pick_id"], int):
        abort(400, "pick_id must be an integer")

    scoring.score_if_expired(user.id, now)
    if scoring.open_attempt(user.id) is not None:
        abort(409, "an attempt is already open")

    attempt = _open_pick(user, body["pick_id"], now)
    db.session.commit()
    return attempt_json(attempt)


@attempt_bp.post("/<int:attempt_id>/done")
def done(attempt_id: int):
    """Ask Codeforces for an Accepted inside the window, and score the attempt.

    One API call (one retry). No Accepted in the window means 409 and the
    attempt stays open — a live timer is not converted into a failure by a
    failed check. An expired timer is scored without calling Codeforces at all.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    attempt = _owned_attempt(attempt_id, user.id)

    if scoring.is_expired(attempt, now):
        scoring.score_attempt(attempt.id, 0, accepted_submission=None, now=now)
        return scored_json(attempt, now)
    if attempt.scored_at is not None:
        return scored_json(attempt, now)  # already scored: hand back its result

    problem = db.session.get(Problem, attempt.problem_id)
    if not user.cf_handle:
        abort(409, "set a Codeforces handle before checking submissions")
    try:
        submissions = codeforces.recent_submissions(user.cf_handle)
    except codeforces.CodeforcesError as exc:
        abort(502, str(exc))

    accepted = _accepted_in_window(submissions, problem, attempt)
    if accepted is None:
        abort(409, "no accepted submission in this attempt's window")

    scoring.score_attempt(attempt.id, 1, accepted_submission=accepted, now=now)
    return scored_json(attempt, now)


@attempt_bp.post("/<int:attempt_id>/give-up")
def give_up(attempt_id: int):
    """S=0, no Codeforces call."""
    user = g.user
    now = datetime.now(timezone.utc)
    attempt = _owned_attempt(attempt_id, user.id)

    if attempt.scored_at is None:
        scoring.score_attempt(attempt.id, 0, accepted_submission=None, now=now)
    return scored_json(attempt, now)


@attempt_bp.post("/<int:attempt_id>/pause")
def pause(attempt_id: int):
    """Freeze the timer while you are interrupted. Idempotent."""
    user = g.user
    now = datetime.now(timezone.utc)
    attempt = _owned_attempt(attempt_id, user.id)

    # A timer that already ran out is scored first, so it cannot be parked: only
    # a live timer can be paused.
    scoring.score_if_expired(user.id, now)
    if attempt.scored_at is not None:
        abort(409, "the attempt is already over")

    scoring.pause_attempt(attempt, now)
    db.session.commit()
    return attempt_json(attempt)


@attempt_bp.post("/<int:attempt_id>/resume")
def resume(attempt_id: int):
    """Restart the timer; the paused time does not count against the window."""
    user = g.user
    now = datetime.now(timezone.utc)
    attempt = _owned_attempt(attempt_id, user.id)

    scoring.score_if_expired(user.id, now)
    if attempt.scored_at is not None:
        abort(409, "the attempt is already over")

    scoring.resume_attempt(attempt, now)
    db.session.commit()
    return attempt_json(attempt)


@attempt_bp.patch("/<int:attempt_id>")
def annotate(attempt_id: int):
    """The key idea and the upsolve flag — the two fields scoring never touches."""
    user = g.user
    now = datetime.now(timezone.utc)
    attempt = _owned_attempt(attempt_id, user.id)
    # An expired attempt is scored first, so annotating is never blocked by a
    # timer that already ran out.
    scoring.score_if_expired(user.id, now)

    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not body:
        abort(400, "send key_idea and/or upsolved")
    unknown = set(body) - set(ANNOTATION_FIELDS)
    if unknown:
        abort(400, f"cannot change {', '.join(sorted(unknown))}")
    if attempt.scored_at is None:
        abort(409, "the attempt is still running")

    if "key_idea" in body:
        key_idea = body["key_idea"]
        if key_idea is not None and not isinstance(key_idea, str):
            abort(400, "key_idea must be text or null")
        attempt.key_idea = key_idea.strip() if isinstance(key_idea, str) else None
    if "upsolved" in body:
        if not isinstance(body["upsolved"], bool):
            abort(400, "upsolved must be true or false")
        attempt.upsolved_at = now if body["upsolved"] else None

    db.session.commit()
    return attempt_json(attempt)


def _owned_attempt(attempt_id: int, user_id: int) -> Attempt:
    attempt = db.session.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user_id:
        abort(404, "no such attempt")
    return attempt


def _open_pick(user, pick_id, now: datetime) -> Attempt:
    pick = db.session.execute(
        select(SessionPick)
        .where(SessionPick.id == pick_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pick is None:
        abort(404, "no such pick")
    if pick.replaced_at is not None or pick.opened_attempt_id is not None:
        abort(409, "that pick is no longer available")

    session = db.session.get(PracticeSession, pick.session_id)
    if session.user_id != user.id:
        abort(404, "no such pick")
    if session.ended_at is not None:
        abort(409, "that session is already finished")

    attempt = Attempt(
        user_id=user.id, problem_id=pick.problem_id, session_id=session.id,
        slot=pick.slot, source="session", rated=pick.slot != "recall", started_at=now,
        p_cal=pick.p_cal,
    )
    db.session.add(attempt)
    db.session.flush()
    pick.opened_attempt_id = attempt.id
    return attempt


def _accepted_in_window(submissions: list[dict], problem: Problem,
                        attempt: Attempt) -> dict | None:
    """The earliest in-window Accepted for this problem, if there is one."""
    deadline = scoring.attempt_deadline(attempt)
    matches = []
    for submission in submissions:
        if codeforces.submission_key(submission) != (problem.contest_id, problem.problem_index):
            continue
        if not codeforces.is_accepted(submission):
            continue
        when = codeforces.submitted_at(submission)
        if when is not None and attempt.started_at <= when <= deadline:
            matches.append((when, submission))
    return min(matches, key=lambda match: match[0])[1] if matches else None
