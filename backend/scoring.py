"""The bridge from the pure rating model to the database.

Everything that writes an attempt, a rating row or a "seen problem" row goes
through here, so the immutable snapshot fields (`s`, `e_model`,
`problem_rating`, `effective_rating`, `overall_after`), the normalised
`AttemptTag` weights and the rating update can never drift apart between the
seed, session, contest-sync and submissions-sync paths.

Callers own the transaction: nothing here commits, so a failure halfway through
a seed or a contest replay rolls back to the last commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from sqlalchemy import func, select

from codeforces import is_accepted, is_contestant, submission_key, submitted_at
from model import (Attempt, AttemptTag, Calibration, Contest, OverallRating, Problem,
                   Revisit, SeenProblem, TopicRating, db)
from model.overall_rating import OVERALL_RD_CAP
from model.topic_rating import TOPIC_RD_CAP
from picking import recall_gap_days
from rating import (NEW_USER_RATING, CalibrationFit, RatingState, aged_rd,
                    fit_calibration, normalised_tag_weights, update_rating)

# The PRD's timer: a scored solve must have been accepted inside this window.
ATTEMPT_MINUTES = 45
ATTEMPT_WINDOW = timedelta(minutes=ATTEMPT_MINUTES)


class ScoreRejected(Exception):
    """The requested score cannot be recorded; routes turn this into a 409."""


def current_overall(user_id: int, now: datetime) -> tuple[float, float]:
    """(rating, aged rd), falling back to the new-user prior when unseeded."""
    overall = db.session.get(OverallRating, user_id)
    if overall is None:
        return NEW_USER_RATING, OVERALL_RD_CAP
    return overall.rating, overall.current_rd(now)


def attempt_deadline(attempt: Attempt) -> datetime:
    """When the timer reaches zero: the window plus every finished pause.

    While the attempt is paused the clock is frozen, so the deadline is not
    moving: the frozen remaining time is `deadline - paused_at`.
    """
    return attempt.started_at + ATTEMPT_WINDOW + timedelta(seconds=attempt.paused_seconds)


def is_expired(attempt: Attempt, now: datetime) -> bool:
    """An open attempt whose 45 minutes are up. A paused attempt never expires."""
    return (
        attempt.scored_at is None
        and attempt.paused_at is None
        and now >= attempt_deadline(attempt)
    )


def pause_attempt(attempt: Attempt, now: datetime) -> None:
    """Freeze the timer. Idempotent: pausing a paused attempt does nothing."""
    if attempt.paused_at is None:
        attempt.paused_at = now


def resume_attempt(attempt: Attempt, now: datetime) -> None:
    """Restart the timer, banking the time spent paused.

    Idempotent, and also the funnel that ends a pause when the attempt is
    scored (scoring an attempt while paused must still finalise it).
    """
    if attempt.paused_at is not None:
        paused = int((now - attempt.paused_at).total_seconds())
        attempt.paused_seconds += max(0, paused)
        attempt.paused_at = None


@dataclass(frozen=True)
class RatingSnapshot:
    """The numbers that must be stored on the attempt that produced them."""

    e_model: float
    effective_rating: float
    overall_after: float
    weights: dict[int, float]


@dataclass(frozen=True)
class ReplayResult:
    """How much of one contest's replay actually moved the rating."""

    problems: int
    skipped: int
    solved: int


def accepted_by_key(submissions: Iterable[dict]) -> dict[tuple[int, str], dict]:
    """The first in-contest Accepted submission per (contest, index).

    Practice-room submissions do not count: the PRD records a contest result
    only for problems the user demonstrably entered that contest with.
    """
    accepted: dict[tuple[int, str], dict] = {}
    for submission in submissions:
        if not is_contestant(submission) or not is_accepted(submission):
            continue
        key = submission_key(submission)
        if key is None:
            continue
        current = accepted.get(key)
        if current is None or (
            submission.get("creationTimeSeconds", 0)
            < current.get("creationTimeSeconds", 0)
        ):
            accepted[key] = submission
    return accepted


def participated_contests(submissions: Iterable[dict]) -> set[int]:
    """Contest ids the user entered — the only contests a failure may be inferred in."""
    return {
        submission["contestId"]
        for submission in submissions
        if is_contestant(submission) and submission.get("contestId") is not None
    }


def mark_seen(user_id: int, problem: Problem, reason: str) -> int:
    """Mark a problem and its Div. 1 / Div. 2 twin as seen, idempotently.

    Duplicate `SeenProblem` rows would violate the (user, problem) primary key,
    so an existing row (whatever its reason) is left alone: the first reason a
    problem was seen is the interesting one.

    Returns how many problems this call newly marked (0 when all were known),
    which is what the submission sync reports as "newly seen".
    """
    problem_ids = [problem.id]
    if problem.twin_group is not None:
        problem_ids = list(db.session.scalars(
            select(Problem.id).where(Problem.twin_group == problem.twin_group)
        ))
    already = set(db.session.scalars(
        select(SeenProblem.problem_id).where(
            SeenProblem.user_id == user_id,
            SeenProblem.problem_id.in_(problem_ids),
        )
    ))
    added = 0
    for problem_id in problem_ids:
        if problem_id not in already:
            db.session.add(
                SeenProblem(user_id=user_id, problem_id=problem_id, reason=reason)
            )
            added += 1
    return added


def topic_weights(problem: Problem) -> dict[int, float]:
    """The problem's tags as normalised weights (generic tags count 0.25)."""
    return normalised_tag_weights([(tag.id, tag.is_generic) for tag in problem.tags])


def rate(user_id: int, problem: Problem, score: int, now: datetime) -> RatingSnapshot:
    """Apply one rated result: update overall + topic rows, return the snapshot.

    RDs are read aged to `now` and written back stamped at `now`, so the aging
    is applied exactly once even though the stored RD is not touched in between.
    """
    if problem.rating is None:
        raise ValueError(f"problem {problem.id} has no rating")

    weights = topic_weights(problem)
    overall_row = db.session.get(OverallRating, user_id)
    if overall_row is None:
        raise LookupError(f"user {user_id} is not seeded")

    topics: dict[int, RatingState] = {}
    topic_rows: dict[int, TopicRating] = {}
    for tag_id in weights:
        row = db.session.get(TopicRating, (user_id, tag_id))
        if row is None:
            # Lazily created the first time a tag participates.
            row = TopicRating(user_id=user_id, tag_id=tag_id,
                              rating_offset=0.0, rd=TOPIC_RD_CAP)
            db.session.add(row)
        topic_rows[tag_id] = row
        topics[tag_id] = RatingState(row.rating_offset, row.rd, row.last_practised_at)

    effective = overall_row.rating + sum(
        weight * topics[tag_id].rating for tag_id, weight in weights.items()
    )
    update = update_rating(
        RatingState(overall_row.rating, overall_row.rd, overall_row.last_practised_at),
        topics, weights, float(problem.rating), score, now,
    )

    overall_row.rating = update.overall.rating
    overall_row.rd = update.overall.rd
    overall_row.last_practised_at = update.overall.last_practised_at
    for tag_id, state in update.topics.items():
        topic_rows[tag_id].rating_offset = state.rating
        topic_rows[tag_id].rd = state.rd
        topic_rows[tag_id].last_practised_at = state.last_practised_at

    return RatingSnapshot(
        e_model=update.e_model,
        effective_rating=effective,
        overall_after=update.overall.rating,
        weights=weights,
    )


def _write_tags(attempt_id: int, weights: Mapping[int, float]) -> None:
    for tag_id, weight in weights.items():
        db.session.add(AttemptTag(attempt_id=attempt_id, tag_id=tag_id, weight=weight))


def _apply_snapshot(attempt: Attempt, problem: Problem, snapshot: RatingSnapshot,
                    score: int, now: datetime) -> None:
    """Write the fields the score-immutability trigger freezes."""
    attempt.s = score
    attempt.scored_at = now
    attempt.e_model = snapshot.e_model
    attempt.problem_rating = problem.rating
    attempt.effective_rating = snapshot.effective_rating
    attempt.overall_after = snapshot.overall_after


def create_scored_attempt(user_id: int, problem: Problem, score: int, *, source: str,
                          started_at: datetime, scored_at: datetime,
                          accepted_at: datetime | None = None,
                          accepted_submission_id: int | None = None,
                          session_id: int | None = None, slot: str | None = None,
                          p_cal: float | None = None, info_factor: float = 1.0,
                          now: datetime | None = None,
                          seen_reason: str = "attempted") -> Attempt:
    """Create an already-scored rated attempt (contest replay, seed).

    `now` is the time the rating update is aged to; it defaults to `scored_at`,
    which is right for replay. Session attempts go through `score_open_attempt`
    instead, because their timer starts when the problem is opened.
    """
    snapshot = rate(user_id, problem, score, now or scored_at)
    attempt = Attempt(
        user_id=user_id, problem_id=problem.id, session_id=session_id, slot=slot,
        source=source, rated=True, started_at=started_at,
        accepted_at=accepted_at, accepted_submission_id=accepted_submission_id,
        p_cal=p_cal, info_factor=info_factor,
    )
    _apply_snapshot(attempt, problem, snapshot, score, scored_at)
    db.session.add(attempt)
    db.session.flush()
    _write_tags(attempt.id, snapshot.weights)
    mark_seen(user_id, problem, seen_reason)
    return attempt


def score_open_attempt(attempt: Attempt, problem: Problem, score: int, now: datetime, *,
                       accepted_at: datetime | None = None,
                       accepted_submission_id: int | None = None) -> Attempt:
    """Score an existing open attempt: snapshot its ratings and mark it seen.

    A rated attempt stores the numbers that produced the update, which is what
    makes replay possible. A recall is unrated (a repeat is not new evidence),
    so it records the result and nothing else: no rating update, no snapshot,
    no tag weights.
    """
    # A scored attempt can never be paused: bank whatever pause was running.
    resume_attempt(attempt, now)
    attempt.accepted_at = accepted_at
    attempt.accepted_submission_id = accepted_submission_id
    if attempt.rated:
        snapshot = rate(attempt.user_id, problem, score, now)
        _apply_snapshot(attempt, problem, snapshot, score, now)
        db.session.flush()
        _write_tags(attempt.id, snapshot.weights)
    else:
        attempt.problem_rating = problem.rating
        attempt.s = score
        attempt.scored_at = now
    mark_seen(attempt.user_id, problem, "attempted")
    return attempt


def contest_start(contest: Contest, submissions: Iterable[dict], fallback: datetime) -> datetime:
    """When a replayed contest happened: catalog start, else its first submission.

    Replay walks contests oldest-first and ages RDs from one contest to the
    next, so every replayed attempt needs a real timestamp.
    """
    if contest.start_time is not None:
        return contest.start_time
    times = [
        submitted_at(submission) for submission in submissions
        if submission.get("contestId") == contest.id and is_contestant(submission)
    ]
    times = [time for time in times if time is not None]
    return min(times) if times else fallback


def replay_contest(user_id: int, contest: Contest, when: datetime,
                   accepted: Mapping[tuple[int, str], dict]) -> ReplayResult:
    """Replay every catalogued problem of one entered contest.

    A problem is S=1 only where an in-contest Accepted exists; everything else
    the user saw in that contest is S=0 (PRD: record the failures too). Problems
    with no rating or no tags cannot produce a rated update, so they are counted
    as skipped but still marked seen.
    """
    problems = db.session.scalars(
        select(Problem).where(Problem.contest_id == contest.id)
        .order_by(Problem.problem_index)
    ).all()

    replayed = skipped = solved = 0
    for problem in problems:
        if problem.rating is None or not problem.tags:
            skipped += 1
            mark_seen(user_id, problem, "contest")
            continue

        submission = accepted.get((contest.id, problem.problem_index))
        create_scored_attempt(
            user_id, problem, 1 if submission is not None else 0,
            source="contest", started_at=when, scored_at=when,
            accepted_at=submitted_at(submission) if submission else None,
            accepted_submission_id=submission.get("id") if submission else None,
            seen_reason="contest",
        )
        replayed += 1
        solved += 1 if submission is not None else 0

    return ReplayResult(problems=replayed, skipped=skipped, solved=solved)


def open_attempt(user_id: int) -> Attempt | None:
    """The user's one running attempt, if any (the timer reads it every request)."""
    return db.session.scalars(
        select(Attempt).where(Attempt.user_id == user_id, Attempt.scored_at.is_(None))
    ).one_or_none()


def score_if_expired(user_id: int, now: datetime) -> Attempt | None:
    """Score a run-out timer before anything else happens.

    Every endpoint that touches an attempt calls this first (PRD: "any call on
    an expired attempt scores it first"), and it scores exactly like give-up:
    S=0 and no Codeforces call.
    """
    attempt = open_attempt(user_id)
    if attempt is None or not is_expired(attempt, now):
        return None
    return score_attempt(attempt.id, 0, accepted_submission=None, now=now)


def lock_attempt(attempt_id: int) -> Attempt | None:
    """The attempt row, locked and refreshed for the rest of the transaction.

    Two requests racing on the same attempt (Done from two tabs, or Done during
    a timer expiry) must not both apply a rating update. The row lock makes the
    second one wait, and `populate_existing` makes it see the first one's
    `scored_at` instead of its own stale copy of the row.
    """
    return db.session.execute(
        select(Attempt)
        .where(Attempt.id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()


def score_attempt(attempt_id: int, score: int, *,
                  accepted_submission: dict | None, now: datetime) -> Attempt:
    """Score one attempt and commit. Idempotent: scoring twice is a no-op.

    This is the only place an open attempt becomes a result, so Done, give-up,
    timer expiry and every "check the deadline first" path all record the same
    numbers, in one transaction with the rating update, the calibration refit
    and the seen rows.
    """
    attempt = lock_attempt(attempt_id)
    if attempt is None:
        raise LookupError(f"no attempt {attempt_id}")
    if attempt.scored_at is not None:
        return attempt  # already scored by another request: hand back its result

    problem = db.session.get(Problem, attempt.problem_id)
    accepted_at = accepted_submission_id = None
    if score == 1:
        if accepted_submission is None:
            raise ScoreRejected("a solve needs the accepted submission")
        accepted_at = submitted_at(accepted_submission)
        accepted_submission_id = accepted_submission.get("id")
        if accepted_at is None or not (
            attempt.started_at <= accepted_at <= attempt_deadline(attempt)
        ):
            raise ScoreRejected("the accepted submission is outside the attempt window")

    score_open_attempt(attempt, problem, score, now,
                       accepted_at=accepted_at,
                       accepted_submission_id=accepted_submission_id)
    if attempt.slot == "recall":
        _close_recall(attempt, now)
    if attempt.in_calibration:
        # PRD: refit after each session attempt, and only those.
        refit_calibration(attempt.user_id, now)
    db.session.commit()
    return attempt


def _close_recall(attempt: Attempt, now: datetime) -> None:
    """Settle the revisit that brought this problem back.

    A failed recall queues the next one, further out: that is what turns one
    recorded failure into "keep repeating it until it is solved first try". A
    first-try solve ends the chain, because nothing is queued for it.

    The pending recall is found through the attempt that queued it, so no extra
    column is needed to link a pick back to its revisit.
    """
    revisit = db.session.scalars(
        select(Revisit)
        .join(Attempt, Attempt.id == Revisit.source_attempt_id)
        .where(Revisit.user_id == attempt.user_id,
               Revisit.kind == "recall",
               Revisit.status == "pending",
               Attempt.problem_id == attempt.problem_id)
    ).first()
    if revisit is not None:
        revisit.status = "served"
        revisit.served_attempt_id = attempt.id
    if attempt.s == 0:
        db.session.add(Revisit(
            user_id=attempt.user_id, source_attempt_id=attempt.id, kind="recall",
            due_on=(now + timedelta(days=recall_gap_days(_recall_lapses(attempt)))).date(),
        ))


def _recall_lapses(attempt: Attempt) -> int:
    """How many recalls of this problem have been failed, this one included."""
    return db.session.scalar(
        select(func.count()).select_from(Attempt).where(
            Attempt.user_id == attempt.user_id,
            Attempt.problem_id == attempt.problem_id,
            Attempt.slot == "recall",
            Attempt.scored_at.isnot(None),
        )
    )


def refit_calibration(user_id: int, now: datetime) -> CalibrationFit:
    """Refit P_cal from every rated session attempt, newest weighted highest."""
    samples = [
        (e_model, s)
        for e_model, s in db.session.execute(
            select(Attempt.e_model, Attempt.s)
            .where(Attempt.user_id == user_id, Attempt.in_calibration)
            .order_by(Attempt.scored_at, Attempt.id)
        )
    ]
    fit = fit_calibration(samples, now)

    row = db.session.get(Calibration, user_id)
    if row is None:
        row = Calibration(user_id=user_id)
        db.session.add(row)
    row.a, row.b, row.n_attempts, row.fitted_at = fit.a, fit.b, fit.n, fit.fitted_at
    return fit


def touch_practised(user_id: int, tag_ids: Iterable[int], now: datetime) -> None:
    """Stamp the overall and topic ratings as practised now.

    The stored RD is aged *before* the stamp is moved forward, so finishing a
    session marks it as the last practice without losing (or double-counting)
    the days that passed since the attempts were scored.
    """
    overall = db.session.get(OverallRating, user_id)
    if overall is not None:
        overall.rd = aged_rd(overall.rd, overall.last_practised_at, OVERALL_RD_CAP, now)
        overall.last_practised_at = now
    for tag_id in set(tag_ids):
        topic = db.session.get(TopicRating, (user_id, tag_id))
        if topic is not None:
            topic.rd = aged_rd(topic.rd, topic.last_practised_at, TOPIC_RD_CAP, now)
            topic.last_practised_at = now
