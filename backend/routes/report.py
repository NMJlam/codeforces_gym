"""Read-only views over the source-of-truth rows: GET /skills and GET /history.

Both are pure projections of `overall_rating`, `topic_ratings`, `sessions` and
`attempts`; nothing here writes or reconstructs history.
"""

from datetime import datetime, timezone

from flask import Blueprint, g
from sqlalchemy import select

from model import Attempt, PracticeSession, Tag, TagGroup, TopicRating, db
from model.topic_rating import TOPIC_RD_CAP
from routes.views import attempt_json
from scoring import current_overall

# An RD at or above this means "we know nothing yet": the tag has never been
# practised, or it has been long enough that the estimate has faded out.
UNKNOWN_RD = 120.0
# A tag whose rating trails the overall by this much is the user's weak spot.
WEAK_GAP = 100.0

report_bp = Blueprint("report", __name__)


def group_ratings(overall: float, tags: list[tuple[str, float, float]]) -> list[dict]:
    """(group, offset, rd) per tag -> one rating per group, sorted by name.

    Precision-weighted mean of the tag offsets, so a well-measured tag counts
    more than one the user has barely touched.
    """
    sums: dict[str, list[float]] = {}
    for group, offset, rd in tags:
        w = 1 / rd**2
        s = sums.setdefault(group, [0.0, 0.0])
        s[0] += w * offset
        s[1] += w
    return [
        {"name": name, "rating": overall + num / den}
        for name, (num, den) in sorted(sums.items())
    ]


@report_bp.get("/skills")
def skills():
    """Every tag's rating and RD, plus the radar-chart group ratings.

    States are advisory labels for the dashboard: not_yet_relevant (the topic
    is above the user's level, i.e. has not emerged), unknown (never practised
    or faded out), weak (well below the overall), strong (otherwise).
    """
    user = g.user
    now = datetime.now(timezone.utc)
    overall, _ = current_overall(user.id, now)

    topic_rows = {
        t.tag_id: t for t in TopicRating.query.filter_by(user_id=user.id)
    }
    tags = []
    group_input: list[tuple[str, float, float]] = []
    for tag_id, name, group, emergence in db.session.execute(
        select(Tag.id, Tag.name, TagGroup.name, Tag.emergence_rating)
        .join(TagGroup, Tag.group_id == TagGroup.id)
        .order_by(Tag.name)
    ):
        topic = topic_rows.get(tag_id)
        offset = topic.rating_offset if topic else 0.0
        rd = topic.current_rd(now) if topic else TOPIC_RD_CAP
        effective = overall + offset
        group_input.append((group, offset, rd))

        if emergence is not None and overall < emergence:
            state = "not_yet_relevant"
        elif topic is None or rd >= UNKNOWN_RD:
            state = "unknown"
        elif offset <= -WEAK_GAP:
            state = "weak"
        else:
            state = "strong"
        tags.append({
            "tag": name,
            "group": group,
            "rating": effective,
            "rd": rd,
            "state": state,
        })

    return {
        "overall": {"rating": overall},
        "groups": group_ratings(overall, group_input),
        "tags": tags,
    }


@report_bp.get("/history")
def history():
    """Sessions (newest first) each with their attempts, plus every attempt twice.

    The flat `attempts` list is convenient for a rating-over-time chart; the
    nested one shows which attempts belong to which session.
    """
    user = g.user
    sessions = db.session.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == user.id)
        .order_by(PracticeSession.started_at.desc(), PracticeSession.id.desc())
    ).all()
    attempts = db.session.scalars(
        select(Attempt)
        .where(Attempt.user_id == user.id)
        .order_by(Attempt.started_at.desc(), Attempt.id.desc())
    ).all()

    by_session: dict[int, list[dict]] = {}
    flat = []
    for attempt in attempts:
        item = attempt_json(attempt)
        flat.append(item)
        if attempt.session_id is not None:
            by_session.setdefault(attempt.session_id, []).append(item)

    tag_names = {
        tag_id: name for tag_id, name in db.session.execute(select(Tag.id, Tag.name))
    }
    return {
        "sessions": [
            {
                "id": session.id,
                "tag": tag_names.get(session.tag_id),
                "started_at": session.started_at.isoformat(),
                "ended_at": session.ended_at.isoformat() if session.ended_at else None,
                "attempts": by_session.get(session.id, []),
            }
            for session in sessions
        ],
        "attempts": flat,
    }
