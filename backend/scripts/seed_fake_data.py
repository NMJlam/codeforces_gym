"""Fill one user with a fake practice history, for looking at the UI.

This is a development tool, not part of the product. It writes straight through
`scoring.py` (never raw INSERTs), so the rating snapshots, the calibration refit
and the seen rows stay exactly as consistent as a real session would leave them,
then backdates the session and attempt timestamps so the dashboard, skills and
history pages have something to show.

The picking half reuses the real route helpers (`_topic_candidates`,
`_pick_problem`) so the problems served here are the ones the app would serve.

    uv run python -m scripts.seed_fake_data                      # dev@example.com
    uv run python -m scripts.seed_fake_data --email you@example.com
    uv run python -m scripts.seed_fake_data --sessions 20 --days 120 --seed 7

Running it wipes the user's practice data first (attempts, sessions, picks,
ratings, calibration), so a second run is not additive.
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

import picking
import scoring
from app import create_app
from flask import current_app
from model import (Attempt, AttemptTag, Calibration, OverallRating, PracticeSession,
                   Problem, Revisit, SeenProblem, SessionPick, TopicRating, User, db)
from model.overall_rating import OVERALL_RD_CAP
from rating import expected_score
from routes.session import _pick_problem, _topic_candidates

MAX_SLOTS_PER_SESSION = 4  # a failed warm-up earns another warm-up
LATENT_SPREAD = 160.0  # per-topic skill swing, so some tags land weak and some strong


def reset_practice(user_id: int) -> None:
    """Delete everything the simulation will rebuild, in FK-safe order."""
    attempt_ids = db.session.query(Attempt.id).filter(Attempt.user_id == user_id)
    session_ids = db.session.query(PracticeSession.id).filter(
        PracticeSession.user_id == user_id
    )
    db.session.query(Revisit).filter(Revisit.user_id == user_id).delete()
    db.session.query(SessionPick).filter(
        SessionPick.session_id.in_(session_ids)
    ).delete(synchronize_session=False)
    db.session.query(AttemptTag).filter(
        AttemptTag.attempt_id.in_(attempt_ids)
    ).delete(synchronize_session=False)
    db.session.query(Attempt).filter(Attempt.user_id == user_id).delete(
        synchronize_session=False
    )
    db.session.query(PracticeSession).filter(
        PracticeSession.user_id == user_id
    ).delete(synchronize_session=False)
    db.session.query(SeenProblem).filter(SeenProblem.user_id == user_id).delete()
    db.session.query(TopicRating).filter(TopicRating.user_id == user_id).delete()
    db.session.query(Calibration).filter(Calibration.user_id == user_id).delete()
    db.session.query(OverallRating).filter(OverallRating.user_id == user_id).delete()
    db.session.flush()


def session_dates(now: datetime, count: int, days: int, rng: random.Random) -> list[datetime]:
    """`count` session times spread over the last `days`, oldest first."""
    step = days / max(1, count)
    cursor = now - timedelta(days=rng.uniform(0.5, 2.0))
    dates = []
    for _ in range(count):
        dates.append(cursor)
        cursor -= timedelta(days=max(0.6, rng.uniform(0.6, 1.4)) * step)
    floor = now - timedelta(days=days)
    return sorted(date for date in dates if date > floor)


def draw_tag(user_id: int, overall: float, when: datetime, rng: random.Random,
             allowed: set[int] | None = None) -> int | None:
    """The app's weighted topic draw, restricted to `allowed` tags if given.

    Without a restriction the draw spreads thin, which leaves every topic at the
    "we know nothing yet" RD. A restriction is what lets a few topics accumulate
    enough attempts to read as strong or weak.
    """
    candidates = _topic_candidates(user_id, overall, when)
    if allowed is not None:
        candidates = [c for c in candidates if c.tag_id in allowed]
    tag_id = picking.draw_topic(candidates, overall, rng)
    if tag_id is not None:
        return tag_id
    usable = [c.tag_id for c in candidates if c.unseen_candidates > 0]
    return rng.choice(usable) if usable else None


def practice_topics(user_id: int, overall: float, when: datetime, count: int) -> set[int]:
    """The `count` best-covered eligible tags at the starting level."""
    eligible = [c for c in _topic_candidates(user_id, overall, when)
                if picking.is_eligible(c, overall)]
    eligible.sort(key=lambda c: -c.near_share)
    return {c.tag_id for c in eligible[:count]}


def run_session(user_id: int, tag_id: int, when: datetime, rng: random.Random,
                latent: float, offsets: dict[int, float]) -> dict:
    """One backdated session: pick a slot, decide the outcome, score it."""
    session = PracticeSession(user_id=user_id, tag_id=tag_id, started_at=when)
    db.session.add(session)
    db.session.flush()

    # A fixed latent skill per topic drives the outcomes, so the fitted ratings
    # converge on it instead of chasing the model's own (still calibrating) guess.
    skill = latent + offsets.setdefault(tag_id, rng.gauss(0.0, LATENT_SPREAD))
    slots: list[tuple[str, int]] = []
    solved = 0
    for _ in range(MAX_SLOTS_PER_SESSION):
        slot = picking.next_slot(slots)
        if slot is None:
            break
        pick = _pick_problem(user_id, session, slot, picking.TARGET_PROBABILITIES[slot], when)
        if pick is None:
            break
        problem = db.session.get(Problem, pick.problem_id)

        score = 1 if rng.random() < expected_score(float(problem.rating), skill) else 0
        solved += score
        started_at = when + timedelta(minutes=rng.randint(5, 30))
        scored_at = started_at + timedelta(minutes=rng.randint(3, 44))
        accepted_at = (
            started_at + timedelta(minutes=rng.randint(4, 40)) if score == 1 else None
        )
        scoring.create_scored_attempt(
            user_id, problem, score, source="session",
            started_at=started_at, scored_at=scored_at,
            accepted_at=accepted_at,
            accepted_submission_id=rng.randint(10 ** 8, 10 ** 9) if score == 1 else None,
            session_id=session.id, slot=slot, p_cal=pick.p_cal,
            now=scored_at,
        )
        scoring.refit_calibration(user_id, scored_at)
        slots.append((slot, score))

    if not slots:
        # Nothing was servable for that tag at that level: drop the shell.
        db.session.delete(session)
        db.session.flush()
        return {"attempts": 0, "solved": 0}

    session.ended_at = when + timedelta(minutes=90)
    scoring.touch_practised(user_id, [tag_id], session.ended_at)
    db.session.flush()
    return {"attempts": len(slots), "solved": solved}


def seed(email: str, sessions: int, days: int, rating: float, seed_value: int,
         topics: int) -> dict:
    user = User.query.filter_by(email=email).one_or_none()
    if user is None:
        # Same seam as the auth hook: the app creates the user on first sign in,
        # so a fresh database has none to fill yet.
        user = User(email=email)
        db.session.add(user)
        db.session.flush()

    total = db.session.query(Problem).count()
    if total == 0:
        raise SystemExit("the catalog is empty: run scripts/populate_codeforces.py first")

    rng = random.Random(seed_value)
    now = datetime.now(timezone.utc)

    reset_practice(user.id)
    db.session.add(OverallRating(user_id=user.id, rating=rating, rd=OVERALL_RD_CAP,
                                 last_practised_at=None))
    db.session.add(Calibration(user_id=user.id, a=0.0, b=1.0, n_attempts=0))
    db.session.flush()

    attempts = solved = sessions_run = 0
    touched: set[int] = set()
    offsets: dict[int, float] = {}
    allowed = practice_topics(user.id, rating, now, topics)
    for when in session_dates(now, sessions, days, rng):
        overall, _ = scoring.current_overall(user.id, when)
        tag_id = draw_tag(user.id, overall, when, rng, allowed)
        if tag_id is None:
            continue
        result = run_session(user.id, tag_id, when, rng, rating, offsets)
        if result["attempts"] == 0:
            continue
        sessions_run += 1
        attempts += result["attempts"]
        solved += result["solved"]
        touched.add(tag_id)

    db.session.commit()

    overall = db.session.get(OverallRating, user.id)
    return {
        "user": email,
        "sessions": sessions_run,
        "attempts": attempts,
        "solved": solved,
        "tags": len(touched),
        "rating": round(overall.rating),
        "rd": round(overall.current_rd(now)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=None,
                        help="the user to fill (default: the app's DEV_EMAIL)")
    parser.add_argument("--sessions", type=int, default=45, help="how many sessions to fabricate")
    parser.add_argument("--days", type=int, default=140, help="how far back to spread them")
    parser.add_argument("--topics", type=int, default=6,
                        help="how many tags to concentrate practice on")
    parser.add_argument("--rating", type=float, default=1400.0,
                        help="the user's latent overall skill (ratings converge on it)")
    parser.add_argument("--seed", type=int, default=1, help="RNG seed, for a repeatable history")
    args = parser.parse_args()

    with create_app().app_context():
        email = args.email or current_app.config["DEV_EMAIL"]
        summary = seed(email, args.sessions, args.days, args.rating, args.seed, args.topics)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
