"""Session lifecycle: start, current, next, replace, finish.

One session is one topic and a short sequence of timed attempts. The route
module owns two things: the SQL that turns the catalog into pickable candidates
(so picking stays a pure function) and the transaction boundaries.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, g, request
from sqlalchemy import delete, exists, func, select

import picking
import scoring
from model import (Attempt, AttemptTag, Calibration, OverallRating, Problem, ProblemTag,
                   PracticeSession, Revisit, SeenProblem, SessionPick, Tag, TopicRating, db)
from model.topic_rating import TOPIC_RD_CAP
from picking import TARGET_PROBABILITIES, TopicCandidate, calibrated_probability
from rating import expected_score
from routes.views import pick_json, session_json

session_bp = Blueprint("sessions", __name__)

# The topic draw and the revisit due dates. Tests swap in a seeded Random so the
# flow is deterministic instead of pinning production randomness.
_rng = random.Random()

REVISIT_MIN_DAYS = 14
REVISIT_MAX_DAYS = 28


@session_bp.post("")
def start_session():
    """Start a session: age the ratings, draw one eligible topic."""
    user = g.user
    now = datetime.now(timezone.utc)

    if db.session.get(OverallRating, user.id) is None:
        abort(409, "seed the ratings before starting a session")
    if _open_session(user.id) is not None:
        abort(409, "a session is already open")
    if scoring.open_attempt(user.id) is not None:
        abort(409, "an attempt is already open")

    overall, _ = scoring.current_overall(user.id, now)
    tag_id = picking.draw_topic(_topic_candidates(user.id, overall, now), overall, _rng)
    if tag_id is None:
        abort(422, "no topic is eligible yet")

    session = PracticeSession(user_id=user.id, tag_id=tag_id, started_at=now)
    db.session.add(session)
    db.session.commit()
    return session_json(session, now)


@session_bp.get("/current")
def current_session():
    """The open session with its picks and results, or 404."""
    user = g.user
    now = datetime.now(timezone.utc)
    scoring.score_if_expired(user.id, now)

    session = _open_session(user.id)
    if session is None:
        abort(404, "no open session")
    return session_json(session, now)


@session_bp.post("/<int:session_id>/next")
def next_pick(session_id: int):
    """Pick the next slot's problem. The timer starts when it is opened.

    The body may name the slot to pick (`{"slot": "main"}`); without one the
    session's own sequence decides, so the guided flow is still the default. A
    due recall is served either way: it is a problem the user already failed,
    and the only way the chain of repeats ever closes is by being solved.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    scoring.score_if_expired(user.id, now)

    session = _owned_open_session(session_id, user.id)
    if _active_pick(session.id) is not None:
        abort(409, "a pick is already waiting to be opened")
    if scoring.open_attempt(user.id) is not None:
        abort(409, "an attempt is already open")

    body = request.get_json(silent=True) or {}
    slot = body.get("slot")
    if slot is not None and slot not in TARGET_PROBABILITIES:
        abort(422, "no such slot")

    due = _due_recall(user.id, now)
    if due is not None:
        pick = _recall_pick(session, due, now)
        db.session.add(pick)
        db.session.commit()
        return pick_json(pick)

    if slot is None:
        slot = picking.next_slot([
            (attempt.slot, attempt.s)
            for attempt in session.attempts if attempt.scored_at is not None
        ])
        if slot is None:
            abort(409, "every slot is done: finish the session")

    pick = _pick_problem(user.id, session, slot, TARGET_PROBABILITIES[slot], now)
    if pick is None:
        abort(422, f"no unseen problem is available for the {slot} slot")

    db.session.add(pick)
    db.session.commit()
    return pick_json(pick)


@session_bp.post("/<int:session_id>/slots/<slot>/replace")
def replace_pick(session_id: int, slot: str):
    """Swap the active pick for another problem at the same target chance.

    The swapped-out problem is marked seen (reason "skipped") and never rated:
    it was never opened, so there is nothing to record.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    scoring.score_if_expired(user.id, now)

    if slot not in TARGET_PROBABILITIES:
        abort(404, "no such slot")
    session = _owned_open_session(session_id, user.id)

    current = db.session.scalars(
        select(SessionPick).where(
            SessionPick.session_id == session.id,
            SessionPick.slot == slot,
            SessionPick.replaced_at.is_(None),
            SessionPick.opened_attempt_id.is_(None),
        )
    ).one_or_none()
    if current is None:
        abort(409, f"no pick is waiting in the {slot} slot")

    scoring.mark_seen(user.id, db.session.get(Problem, current.problem_id), "skipped")
    current.replaced_at = now

    replacement = _pick_problem(user.id, session, slot, current.target_probability, now)
    if replacement is None:
        abort(422, f"no other unseen problem is available for the {slot} slot")
    db.session.add(replacement)
    db.session.commit()
    return pick_json(replacement)


@session_bp.post("/<int:session_id>/picks/<int:pick_id>/cancel")
def cancel_pick(session_id: int, pick_id: int):
    """Go back to the slot picker: drop a pick that has not been opened yet.

    Nothing was attempted, so nothing is recorded and the problem is not marked
    seen -- unlike replace, which retires the problem as a skip and picks
    another at the same chance. The slot is freed for another choice.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    scoring.score_if_expired(user.id, now)

    session = _owned_open_session(session_id, user.id)
    pick = db.session.get(SessionPick, pick_id)
    if pick is None or pick.session_id != session.id:
        abort(404, "no such pick")
    if pick.replaced_at is not None or pick.opened_attempt_id is not None:
        abort(409, "that pick is not waiting to be opened")

    db.session.delete(pick)
    db.session.commit()
    return session_json(session, now)


@session_bp.post("/<int:session_id>/finish")
def finish_session(session_id: int):
    """Close the session: queue revisits for failures, mark the topics practised.

    Finishing an already-finished session returns its summary unchanged, so a
    retried request cannot queue a second round of revisits. A session with
    nothing attempted in it is not recorded at all: the row is dropped and the
    topic it drew is freed, since an empty run is not history.
    """
    user = g.user
    now = datetime.now(timezone.utc)
    scoring.score_if_expired(user.id, now)

    session = _owned_session(session_id, user.id)
    if session.ended_at is not None:
        return session_json(session, now)
    if scoring.open_attempt(user.id) is not None:
        abort(409, "an attempt is still running")

    # An unopened pick is not a result: nothing was attempted, so nothing is
    # recorded (Attempt only exists once the timer starts).
    db.session.execute(
        delete(SessionPick).where(
            SessionPick.session_id == session.id,
            SessionPick.replaced_at.is_(None),
            SessionPick.opened_attempt_id.is_(None),
        )
    )

    if not session.attempts:
        # Nothing was attempted in here at all, so there is no run to keep: the
        # session is dropped rather than left behind as an empty one. A running
        # attempt cannot reach this point (it aborts above) and an expired one
        # was scored above, so "no attempts" means exactly "nothing happened".
        # The summary still comes back, with `ended_at` set, so the response
        # shape does not depend on this branch; a repeated finish is a 404,
        # because the session is genuinely gone.
        session.ended_at = now
        body = session_json(session, now)
        db.session.delete(session)
        db.session.commit()
        return body

    attempted = [
        attempt for attempt in session.attempts
        if attempt.scored_at is not None and attempt.rated
    ]
    tag_ids = list(db.session.scalars(
        select(AttemptTag.tag_id)
        .where(AttemptTag.attempt_id.in_([attempt.id for attempt in attempted]))
        .distinct()
    ))
    for attempt in attempted:
        scoring.mark_seen(user.id, db.session.get(Problem, attempt.problem_id), "attempted")
        if attempt.s == 0:
            _queue_revisits(attempt, now)

    scoring.touch_practised(user.id, tag_ids, now)
    session.ended_at = now
    db.session.commit()
    return session_json(session, now)


# --- shared helpers ---------------------------------------------------------

def _open_session(user_id: int) -> PracticeSession | None:
    return db.session.scalars(
        select(PracticeSession).where(
            PracticeSession.user_id == user_id,
            PracticeSession.ended_at.is_(None),
        )
    ).one_or_none()


def _owned_session(session_id: int, user_id: int) -> PracticeSession:
    session = db.session.get(PracticeSession, session_id)
    if session is None or session.user_id != user_id:
        abort(404, "no such session")
    return session


def _owned_open_session(session_id: int, user_id: int) -> PracticeSession:
    session = _owned_session(session_id, user_id)
    if session.ended_at is not None:
        abort(409, "that session is already finished")
    return session


def _active_pick(session_id: int) -> SessionPick | None:
    return db.session.scalars(
        select(SessionPick).where(
            SessionPick.session_id == session_id,
            SessionPick.replaced_at.is_(None),
            SessionPick.opened_attempt_id.is_(None),
        )
    ).one_or_none()


def _topic_candidates(user_id: int, overall: float, now: datetime) -> list[TopicCandidate]:
    """Every tag as the topic draw sees it, with the near-level counts from SQL."""
    low, high = overall - picking.NEAR_WINDOW, overall + picking.NEAR_WINDOW

    total = db.session.scalar(
        select(func.count()).select_from(Problem).where(Problem.rating.between(low, high))
    )
    tagged = {
        tag_id: count for tag_id, count in db.session.execute(
            select(ProblemTag.tag_id, func.count())
            .join(Problem, Problem.id == ProblemTag.problem_id)
            .where(Problem.rating.between(low, high))
            .group_by(ProblemTag.tag_id)
        )
    }
    unseen = {
        tag_id: count for tag_id, count in db.session.execute(
            select(ProblemTag.tag_id, func.count())
            .join(Problem, Problem.id == ProblemTag.problem_id)
            .where(Problem.rating.between(low, high),
                   ~exists().where((SeenProblem.user_id == user_id)
                                   & (SeenProblem.problem_id == Problem.id)))
            .group_by(ProblemTag.tag_id)
        )
    }

    practised = {row.tag_id: row for row in TopicRating.query.filter_by(user_id=user_id)}
    candidates = []
    for tag_id, tier_weight, emergence in db.session.execute(
        select(Tag.id, Tag.tier_weight, Tag.emergence_rating)
    ):
        row = practised.get(tag_id)
        days = None
        if row is not None and row.last_practised_at is not None:
            days = (now - row.last_practised_at).total_seconds() / 86400.0
        candidates.append(TopicCandidate(
            tag_id=tag_id,
            tier_weight=tier_weight,
            emergence_rating=emergence,
            offset=row.rating_offset if row else 0.0,
            rd=row.current_rd(now) if row else TOPIC_RD_CAP,
            days_since_practised=days,
            near_share=(tagged.get(tag_id, 0) / total) if total else 0.0,
            unseen_candidates=unseen.get(tag_id, 0),
        ))
    return candidates


def _due_recall(user_id: int, now: datetime) -> tuple[Revisit, Problem] | None:
    """The oldest recall that has come due, with the problem to serve again."""
    row = db.session.execute(
        select(Revisit, Problem)
        .join(Attempt, Attempt.id == Revisit.source_attempt_id)
        .join(Problem, Problem.id == Attempt.problem_id)
        .where(Revisit.user_id == user_id,
               Revisit.kind == "recall",
               Revisit.status == "pending",
               Revisit.due_on <= now.date())
        .order_by(Revisit.due_on, Revisit.id)
        .limit(1)
    ).first()
    return tuple(row) if row is not None else None


def _recall_pick(session: PracticeSession, due: tuple[Revisit, Problem],
                 now: datetime) -> SessionPick:
    """The repeat of a failed problem, built like any other pick.

    The database slot is "recall" -- that is what keeps its attempt unrated --
    but nothing in the response points at the repeat: see routes.views. The
    chance is recomputed from today's ratings, and the target is whatever the
    original pick aimed for, so the numbers shown are honest about a problem
    that is served again rather than chosen for a target.
    """
    revisit, problem = due
    source = db.session.get(Attempt, revisit.source_attempt_id)
    p_cal = _calibrated_chance(session.user_id, problem, now)
    return SessionPick(
        session_id=session.id, position=_next_position(session.id), slot="recall",
        problem_id=problem.id,
        target_probability=source.p_cal if source.p_cal else p_cal,
        p_cal=p_cal, picked_at=now,
    )


def _calibrated_chance(user_id: int, problem: Problem, now: datetime) -> float:
    """What the model believes the user's chance on `problem` is right now.

    The effective rating is the same one `scoring.rate` would use: the problem's
    own tags, weighted, against the overall rating -- so a repeat of a problem
    from another topic still reports a number this model stands behind.
    """
    if problem.rating is None:
        return 0.5
    overall, _ = scoring.current_overall(user_id, now)
    effective = overall
    for tag_id, weight in scoring.topic_weights(problem).items():
        topic = db.session.get(TopicRating, (user_id, tag_id))
        effective += weight * (topic.rating_offset if topic is not None else 0.0)
    calibration = db.session.get(Calibration, user_id)
    a, b = (calibration.a, calibration.b) if calibration else (0.0, 1.0)
    return calibrated_probability(expected_score(problem.rating, effective), a, b)


def _next_position(session_id: int) -> int:
    return db.session.scalar(
        select(func.coalesce(func.max(SessionPick.position), -1) + 1)
        .where(SessionPick.session_id == session_id)
    )


def _pick_problem(user_id: int, session: PracticeSession, slot: str, target: float,
                  now: datetime) -> SessionPick | None:
    """Choose and build (but do not commit) one pick for a slot."""
    overall, _ = scoring.current_overall(user_id, now)
    topic = db.session.get(TopicRating, (user_id, session.tag_id))
    effective = overall + (topic.rating_offset if topic else 0.0)

    calibration = db.session.get(Calibration, user_id)
    a, b = (calibration.a, calibration.b) if calibration else (0.0, 1.0)
    target_rating = picking.target_rating(target, effective, a, b)

    low, high = target_rating - picking.CANDIDATE_WINDOW, target_rating + picking.CANDIDATE_WINDOW
    rows = db.session.execute(
        select(Problem.id, Problem.rating, Problem.solved_count)
        .join(ProblemTag, ProblemTag.problem_id == Problem.id)
        .where(ProblemTag.tag_id == session.tag_id, Problem.rating.between(low, high))
    ).all()
    infos = [
        picking.ProblemInfo(problem_id=problem_id, rating=rating, solved_count=solved_count,
                            tags=_problem_tags(problem_id))
        for problem_id, rating, solved_count in rows
    ]

    seen = set(db.session.scalars(
        select(SeenProblem.problem_id).where(SeenProblem.user_id == user_id)
    ))
    candidates = [
        picking.problem_candidate(info, effective_rating=effective,
                                  topic_tag_id=session.tag_id, a=a, b=b)
        for info in picking.selectable(infos, seen)
    ]
    chosen = picking.choose_problem(candidates, target)
    if chosen is None:
        return None

    position = _next_position(session.id)
    return SessionPick(
        session_id=session.id, position=position, slot=slot,
        problem_id=chosen.problem_id, target_probability=target,
        p_cal=chosen.p_cal, picked_at=now,
    )


def _problem_tags(problem_id: int) -> tuple[tuple[int, bool], ...]:
    return tuple(db.session.execute(
        select(ProblemTag.tag_id, Tag.is_generic)
        .join(Tag, Tag.id == ProblemTag.tag_id)
        .where(ProblemTag.problem_id == problem_id)
    ).all())


def _queue_revisits(attempt: Attempt, now: datetime) -> None:
    """One related (new problem) and one recall (the same problem) per failure.

    The recall is the first link of the repeat chain: the problem comes back in
    a week and keeps coming back, further out each time it is failed, until it
    is solved first try. The related follow-up is the transfer dose and keeps
    its 2-4 weeks. A failure can only queue each kind once, so a repeated
    finish cannot double up.
    """
    due = {
        "related": _rng.randint(REVISIT_MIN_DAYS, REVISIT_MAX_DAYS),
        "recall": picking.recall_gap_days(0),
    }
    for kind, days in due.items():
        db.session.add(Revisit(
            user_id=attempt.user_id,
            source_attempt_id=attempt.id,
            kind=kind,
            due_on=(now + timedelta(days=days)).date(),
        ))
