"""Read-only views over the source-of-truth rows: GET /skills and GET /history.

Both are pure projections of `overall_rating`, `topic_ratings`, `sessions` and
`attempts`; nothing here writes or reconstructs history.
"""

from datetime import datetime, timezone

from flask import Blueprint, g, request
from sqlalchemy import Text, cast, func, or_, select

from model import Attempt, Problem, Tag, TagGroup, TopicRating, db
from model.topic_rating import TOPIC_RD_CAP
from routes.views import attempt_json
from scoring import current_overall

# An RD at or above this means "we know nothing yet": the tag has never been
# practised, or it has been long enough that the estimate has faded out.
UNKNOWN_RD = 120.0
# A tag whose rating trails the overall by this much is the user's weak spot.
WEAK_GAP = 100.0

# The attempt log only grows, so GET /history pages it when asked. A request
# that names none of `q`/`page`/`per_page` still gets the whole log: the
# dashboard's charts read every attempt, and the session store looks for a
# running one.
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

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


def _ordered_attempts(user_id: int):
    """The user's attempts, newest first — the order every history view wants."""
    return (
        select(Attempt)
        .where(Attempt.user_id == user_id)
        .order_by(Attempt.started_at.desc(), Attempt.id.desc())
    )


def _matching(query, search: str):
    """Narrow the log to the attempts whose problem or note mentions `search`.

    A past question is found by its name, its "1234A" handle, its index alone,
    or whatever the user wrote in the key idea; the value is a substring,
    case-folded by ILIKE.
    """
    if not search:
        return query
    pattern = f"%{search}%"
    handle = cast(Problem.contest_id, Text) + Problem.problem_index
    return query.join(Problem, Problem.id == Attempt.problem_id).where(
        or_(
            Problem.name.ilike(pattern),
            handle.ilike(pattern),
            Problem.problem_index.ilike(pattern),
            Attempt.key_idea.ilike(pattern),
        )
    )


@report_bp.get("/history")
def history():
    """The attempt log: every question the user attempted, newest first.

    `q`, `page` and `per_page` page and search it: a `q` matches a problem's
    name, its "1234A" handle or the attempt's key idea. A request that names
    none of the three gets the whole log, which is what the dashboard's charts
    read.
    """
    user = g.user
    search = (request.args.get("q") or "").strip()
    paged = bool(search) or "page" in request.args or "per_page" in request.args
    page = max(1, request.args.get("page", default=1, type=int))
    per_page = min(
        MAX_PAGE_SIZE,
        max(1, request.args.get("per_page", default=DEFAULT_PAGE_SIZE, type=int)),
    )

    query = _matching(_ordered_attempts(user.id), search)
    listed = query.limit(per_page).offset((page - 1) * per_page) if paged else query
    attempts = db.session.scalars(listed).all()

    total = db.session.scalar(
        select(func.count()).select_from(
            _matching(select(Attempt.id).where(Attempt.user_id == user.id), search).subquery()
        )
    )
    # The header sentence counts the whole log, not the page or the search:
    # "rated" is a scored attempt, the ones the rating engine consumed.
    rated_total, solved_total = db.session.execute(
        select(
            func.count().filter(Attempt.scored_at.isnot(None)),
            func.count().filter(Attempt.s == 1),
        ).where(Attempt.user_id == user.id)
    ).one()

    return {
        "attempts": [attempt_json(attempt) for attempt in attempts],
        "attempts_total": total,
        "rated_total": rated_total,
        "solved_total": solved_total,
        # An unpaged reply is one page holding everything, which is what the
        # dashboard and the session store assume.
        "page": page if paged else 1,
        "per_page": per_page if paged else total,
        # Echoed so the client can describe the reply without guessing which
        # keystroke it belongs to.
        "q": search,
    }
