from datetime import datetime, timedelta, timezone

import codeforces
from flask import Blueprint, abort, g, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import scoring
from model import Attempt, Calibration, Contest, OverallRating, Tag, TagGroup, TopicRating, db
from model.overall_rating import OVERALL_RD_CAP
from model.topic_rating import TOPIC_RD_CAP
from rating import initial_overall_rating
from routes.report import group_ratings
from scoring import current_overall

user_bp = Blueprint("users", __name__)


@user_bp.route("/me")
def me():
    """Everything the dashboard needs in one call.

    history covers the past year; the frontend filters week/month/year itself.

    `seeded` is the authoritative "the account has been set up" bit: the same
    `overall_rating` row that `PUT /me`, `POST /me/seed` and `POST /sessions`
    test. Clients must not infer it from the rating or the groups, which look
    like the new-user prior whether or not a seed ever ran.
    """
    u = g.user
    now = datetime.now(timezone.utc)
    # Not seeded yet: show the new-user prior (800 +/- 350, every offset 0).
    rating, rd = current_overall(u.id, now)

    topics = {t.tag_id: t for t in TopicRating.query.filter_by(user_id=u.id)}
    tags = []
    for tag_id, group in db.session.execute(
        select(Tag.id, TagGroup.name).join(TagGroup, Tag.group_id == TagGroup.id)
    ):
        t = topics.get(tag_id)  # untouched tag: offset 0 +/- cap
        tags.append(
            (group, t.rating_offset, t.current_rd(now))
            if t
            else (group, 0.0, TOPIC_RD_CAP)
        )

    history = db.session.execute(
        select(Attempt.scored_at, Attempt.overall_after)
        .where(
            Attempt.user_id == u.id,
            Attempt.rated,
            Attempt.scored_at >= now - timedelta(days=365),
        )
        .order_by(Attempt.scored_at, Attempt.id)
    )
    return {
        "id": u.id,
        "email": u.email,
        "cf_handle": u.cf_handle,
        "seeded": db.session.get(OverallRating, u.id) is not None,
        "rating": {"rating": rating, "rd": rd},
        "groups": group_ratings(rating, tags),
        "history": [{"t": t.isoformat(), "rating": r} for t, r in history],
    }


@user_bp.put("/me")
def update_me():
    """Save the Codeforces handle used for every CF API call.

    Once ratings are seeded the handle is frozen: the seeded history belongs to
    a specific Codeforces account, so pointing the same ratings at a different
    one would silently mix two identities' results. Changing it would need a
    destructive reseed, so it is a 409, not a silent update.
    """
    body = request.get_json(silent=True)
    handle = body.get("cf_handle") if isinstance(body, dict) else None
    if not isinstance(handle, str) or not handle.strip():
        abort(400, "cf_handle is required")

    u = g.user
    handle = handle.strip()
    if u.cf_handle == handle:
        return {"cf_handle": u.cf_handle}
    if db.session.get(OverallRating, u.id) is not None:
        abort(409, "cf_handle is locked after seeding")

    u.cf_handle = handle
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(409, "cf_handle already in use")
    return {"cf_handle": u.cf_handle}


@user_bp.post("/me/seed")
def seed():
    """One-time rating seed: replay the handle's Codeforces history.

    Everything happens in one transaction and one commit. A Codeforces failure,
    a missing catalog entry or a rating error rolls the whole seed back, so a
    retry always starts from "not seeded" rather than from half a history.
    """
    user = g.user
    if not user.cf_handle:
        abort(400, "cf_handle is required before seeding")
    if db.session.get(OverallRating, user.id) is not None:
        abort(409, "ratings are already seeded")

    try:
        profile = codeforces.user_info(user.cf_handle)
        codeforces.pace()
        rating_history = codeforces.user_rating(user.cf_handle)
        codeforces.pace()
        submissions = codeforces.user_status(user.cf_handle)
    except codeforces.CodeforcesError as exc:
        abort(502, str(exc))

    now = datetime.now(timezone.utc)
    entered = scoring.participated_contests(submissions) | {
        row["contestId"] for row in rating_history if row.get("contestId") is not None
    }
    contests = db.session.scalars(
        select(Contest).where(Contest.id.in_(entered))
    ).all() if entered else []
    if entered and not contests:
        # Nothing to map against: seeding now would silently skip the history.
        abort(409, "catalog is not synced: none of the handle's contests are known")

    starts = {contest.id: scoring.contest_start(contest, submissions, now) for contest in contests}
    contests.sort(key=lambda c: (starts[c.id], c.id))

    initial = initial_overall_rating(profile.get("rating"), len(rating_history))
    accepted = scoring.accepted_by_key(submissions)

    try:
        db.session.add(OverallRating(
            user_id=user.id, rating=initial, rd=OVERALL_RD_CAP, last_practised_at=None,
        ))
        # Calibration starts at the priors and refits after each session attempt.
        db.session.add(Calibration(user_id=user.id, a=0.0, b=1.0, n_attempts=0))
        db.session.flush()

        replay = {"replayed": 0, "problems": 0, "skipped": 0, "solved": 0}
        for contest in contests:
            result = scoring.replay_contest(user.id, contest, starts[contest.id], accepted)
            replay["replayed"] += 1
            replay["problems"] += result.problems
            replay["skipped"] += result.skipped
            replay["solved"] += result.solved
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    overall = db.session.get(OverallRating, user.id)
    return {
        "rating": {"rating": overall.rating, "rd": overall.current_rd(now)},
        "contests": {"replayed": replay["replayed"], "skipped": len(entered) - replay["replayed"]},
        "problems": {
            "replayed": replay["problems"],
            "skipped": replay["skipped"],
            "solved": replay["solved"],
        },
    }
