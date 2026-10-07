"""JSON shapes for the session and attempt API.

One module because one rule matters more than the individual fields: a problem's
tags are never exposed, and a pick never exposes the editorial. Both exist to
keep "no hints or tags during an attempt" true, and that only holds if there is
a single place that turns rows into responses.

The default for `problem_json` is the strict one (no editorial), so a new caller
that forgets the flag leaks nothing.
"""

from __future__ import annotations

from datetime import datetime

import scoring
from model import Attempt, PracticeSession, Problem, SessionPick, Tag, db
from picking import SESSION_SLOTS, next_slot

# A recall is a repeat of a problem the user already failed, and the API never
# says so while the problem is being served: `slot` reports the role the pick
# plays in the session, not the bookkeeping value that keeps its attempt
# unrated. Once the attempt is scored, `attempt_json` switches to the real slot,
# so history shows a repeat for what it was.
VISIBLE_SLOTS = {"recall": "warmup", "revisit": "warmup"}


def _visible_slot(slot: str | None) -> str | None:
    return VISIBLE_SLOTS.get(slot, slot)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def problem_json(problem: Problem, *, editorial: bool = False) -> dict:
    payload = {
        "contest_id": problem.contest_id,
        "index": problem.problem_index,
        "name": problem.name,
        "rating": problem.rating,
    }
    if editorial:
        # Codeforces exposes no editorial flag, so this is the search string the
        # user pastes into a search engine once the attempt is over.
        payload["editorial_search"] = problem.editorial_search
    return payload


def attempt_json(attempt: Attempt) -> dict:
    """One attempt. No tag rows, ever: not while it is open, not afterwards.

    The editorial search string waits for the score, for the same reason: an
    open attempt must not carry a hint, and this serializer is also what
    GET /history uses.
    """
    problem = db.session.get(Problem, attempt.problem_id)
    return {
        "id": attempt.id,
        "source": attempt.source,
        # The real slot only once the attempt is over; before that a repeat must
        # not announce itself.
        "slot": attempt.slot if attempt.scored_at is not None else _visible_slot(attempt.slot),
        "problem": problem_json(problem, editorial=attempt.scored_at is not None),
        "started_at": iso(attempt.started_at),
        "deadline": iso(scoring.attempt_deadline(attempt)),
        "paused_at": iso(attempt.paused_at),
        "scored_at": iso(attempt.scored_at),
        "accepted_at": iso(attempt.accepted_at),
        "accepted_submission_id": attempt.accepted_submission_id,
        "s": attempt.s,
        "rated": attempt.rated,
        "p_cal": attempt.p_cal,
        "e_model": attempt.e_model,
        "problem_rating": attempt.problem_rating,
        "effective_rating": attempt.effective_rating,
        "overall_after": attempt.overall_after,
        "key_idea": attempt.key_idea,
        "upsolved_at": iso(attempt.upsolved_at),
    }


def scored_json(attempt: Attempt, now: datetime) -> dict:
    """A just-scored attempt: its score, the rating it moved, its editorial."""
    rating, rd = scoring.current_overall(attempt.user_id, now)
    return {**attempt_json(attempt), "rating": {"rating": rating, "rd": rd}}


def pick_json(pick: SessionPick) -> dict:
    """A picked problem, before its timer starts. No editorial: that is a hint."""
    return {
        "id": pick.id,
        "session_id": pick.session_id,
        "position": pick.position,
        "slot": _visible_slot(pick.slot),
        "problem": problem_json(db.session.get(Problem, pick.problem_id)),
        "target_probability": pick.target_probability,
        "p_cal": pick.p_cal,
        "picked_at": iso(pick.picked_at),
    }


def session_json(session: PracticeSession, now: datetime) -> dict:
    """The open session as the UI sees it: what is picked, what happened, next."""
    rating, rd = scoring.current_overall(session.user_id, now)
    scored = [attempt for attempt in session.attempts if attempt.scored_at is not None]
    pending = [
        pick for pick in session.picks
        if pick.replaced_at is None and pick.opened_attempt_id is None
    ]
    return {
        "id": session.id,
        "tag": db.session.get(Tag, session.tag_id).name,
        "started_at": iso(session.started_at),
        "ended_at": iso(session.ended_at),
        "next_slot": next_slot([
            (attempt.slot, attempt.s) for attempt in scored
            if attempt.slot in SESSION_SLOTS
        ]),
        "picks": [pick_json(pick) for pick in pending],
        "attempts": [attempt_json(attempt) for attempt in session.attempts],
        "overall": {"rating": rating, "rd": rd},
    }
