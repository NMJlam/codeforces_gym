"""Catalog sync (PRD "Catalog" layer): problems, tags, contests, emergence.

Rebuildable from the Codeforces API, so it is safe to re-run. Never polled in
the background (PRD constraint); it runs when POSTed, at ~1 call / 2 s.
"""

import re
from datetime import datetime, timezone

from flask import Blueprint, abort, g
from sqlalchemy import select

import codeforces
import scoring
from model import (Attempt, Contest, OverallRating, Problem, ProblemTag, Tag, db)

DIVISION_RE = re.compile(r"Div\.?\s*(\d)", re.IGNORECASE)
EMERGENCE_SHARE = 0.03  # a tag emerges at the first rating bucket where its
EMERGENCE_WINDOW = 200  # ±200-window share of rated problems reaches 3%

sync_bp = Blueprint("sync", __name__)


def parse_division(name: str) -> str | None:
    m = DIVISION_RE.search(name)
    return f"Div. {m.group(1)}" if m else None


def assign_twin_groups(problems: list[dict]) -> dict[tuple[int, str], int]:
    """Div 1/2 parallel rounds share consecutive contest ids and problem names."""
    by_contest: dict[int, list[dict]] = {}
    for p in problems:
        by_contest.setdefault(p["contestId"], []).append(p)

    twin_group: dict[tuple[int, str], int] = {}
    next_group = 1
    for contest_id, probs in by_contest.items():
        other = by_contest.get(contest_id - 1)
        if not other:
            continue
        names_other = {p["name"]: p for p in other}
        for p in probs:
            match = names_other.get(p["name"])
            if not match:
                continue
            key_a = (contest_id, p["index"])
            key_b = (contest_id - 1, match["index"])
            group = twin_group.get(key_b, next_group)
            if group == next_group:
                next_group += 1
            twin_group[key_a] = group
            twin_group[key_b] = group
    return twin_group


def emergence_ratings(samples: list[tuple[int, list[str]]]) -> dict[str, int]:
    """tag -> first rating bucket whose ±200-window share of rated problems is
    at least EMERGENCE_SHARE. Tags that never get there are absent.

    Covers sparse/gym histories: a tag with no problems near the user's level
    simply never becomes eligible.
    """
    samples = [(rating, set(tags)) for rating, tags in samples if rating and tags]
    buckets = sorted({rating for rating, _ in samples})
    counts: dict[tuple[str, int], int] = {}
    totals: dict[int, int] = {}
    for bucket in buckets:
        window = [tags for rating, tags in samples
                  if bucket - EMERGENCE_WINDOW <= rating <= bucket + EMERGENCE_WINDOW]
        totals[bucket] = len(window)
        for tags in window:
            for tag in tags:
                key = (tag, bucket)
                counts[key] = counts.get(key, 0) + 1

    out: dict[str, int] = {}
    for (tag, bucket), n in counts.items():
        if n / totals[bucket] >= EMERGENCE_SHARE and (
            tag not in out or bucket < out[tag]
        ):
            out[tag] = bucket
    return out


def _upsert_contests(contests: list[dict]) -> None:
    for c in contests:
        contest = db.session.get(Contest, c["id"]) or Contest(id=c["id"])
        contest.name = c["name"]
        contest.division = parse_division(c["name"])
        contest.start_time = (
            datetime.fromtimestamp(c["startTimeSeconds"], tz=timezone.utc)
            if "startTimeSeconds" in c else None
        )
        db.session.add(contest)
    db.session.flush()


def _upsert_tags(names: set[str]) -> dict[str, int]:
    existing = {t.name: t.id for t in db.session.query(Tag).all()}
    for name in names - existing.keys():
        tag = Tag(name=name)
        db.session.add(tag)
        db.session.flush()
        existing[name] = tag.id
    return existing


def _upsert_problems(problems: list[dict], stats: dict[tuple[int, str], int],
                     tag_ids: dict[str, int]) -> None:
    groups = assign_twin_groups(problems)
    known_contest_ids = {row.id for row in db.session.query(Contest.id)}
    for p in problems:
        if p["contestId"] not in known_contest_ids:
            continue
        row = (
            db.session.query(Problem)
            .filter_by(contest_id=p["contestId"], problem_index=p["index"])
            .one_or_none()
            or Problem(contest_id=p["contestId"], problem_index=p["index"])
        )
        row.name = p["name"]
        row.rating = p.get("rating")
        row.solved_count = stats.get((p["contestId"], p["index"]), 0)
        row.twin_group = groups.get((p["contestId"], p["index"]))
        db.session.add(row)
        db.session.flush()

        want = {tag_ids[t] for t in p.get("tags", [])}
        have = {
            pt.tag_id
            for pt in db.session.query(ProblemTag).filter_by(problem_id=row.id)
        }
        for tag_id in want - have:
            db.session.add(ProblemTag(problem_id=row.id, tag_id=tag_id))
        for tag_id in have - want:
            db.session.query(ProblemTag).filter_by(
                problem_id=row.id, tag_id=tag_id
            ).delete()


def sync_catalog() -> dict:
    """Refetch contests + problems and recompute tag emergence ratings."""
    contests = codeforces.call("contest.list")
    codeforces.pace()
    result = codeforces.call("problemset.problems")

    # Problems without a contestId (gym / problemset-only) have nowhere to
    # attach: problems.contest_id is a NOT NULL FK to contests. Special
    # problems ("*special" tag) are excluded outright (PRD: Exclude *special).
    problems = [p for p in result["problems"]
                if "contestId" in p and "*special" not in p.get("tags", [])]
    stats = {(s["contestId"], s["index"]): s["solvedCount"]
             for s in result["problemStatistics"]}

    _upsert_contests(contests)
    tag_ids = _upsert_tags({t for p in problems for t in p.get("tags", [])})
    _upsert_problems(problems, stats, tag_ids)

    emergence = emergence_ratings(
        [(p.get("rating"), p.get("tags", [])) for p in problems]
    )
    for name, rating in emergence.items():
        db.session.query(Tag).filter_by(name=name).update({"emergence_rating": rating})

    db.session.commit()
    return {"problems": len(problems), "tags": len(tag_ids), "emergence": len(emergence)}


@sync_bp.post("/catalog")
def sync_catalog_route() -> dict:
    """Populate problems, tags and emergence ratings from the Codeforces API."""
    return sync_catalog()


@sync_bp.post("/submissions")
def sync_submissions():
    """Log the handle's outside solves as seen problems -- never as attempts.

    An Accepted in the practice room means the problem is no longer a candidate
    for a fresh rated attempt, and nothing more: no attempt row, no rating, no
    calibration. Re-running it is a no-op.
    """
    user = g.user
    if not user.cf_handle:
        abort(400, "cf_handle is required before syncing submissions")

    try:
        submissions = codeforces.user_status(user.cf_handle)
    except codeforces.CodeforcesError as exc:
        abort(502, str(exc))

    # Any Accepted counts here (practice-room submissions included): the point
    # is "the user has already solved this", not "they solved it in a contest".
    accepted = set()
    for submission in submissions:
        if codeforces.is_accepted(submission):
            key = codeforces.submission_key(submission)
            if key is not None:
                accepted.add(key)

    mapped = 0
    newly_seen = 0
    for problem in _catalog_problems(accepted):
        mapped += 1
        newly_seen += scoring.mark_seen(user.id, problem, "external")
    db.session.commit()
    return {
        "fetched": len(submissions),
        "accepted": len(accepted),
        "mapped": mapped,
        "newly_seen": newly_seen,
    }


@sync_bp.post("/contests")
def sync_contests():
    """Replay the contests the handle entered and that have no attempts yet.

    A contest is "new" when nothing in it has been replayed: that covers both a
    round finished since the last sync and one whose problems only reached the
    local catalog afterwards. Problems are replayed with the same path as the
    seed (S=1 for an in-contest Accepted, else 0), and everything commits once
    per invocation, so a failure replays nothing half-way.
    """
    user = g.user
    if not user.cf_handle:
        abort(400, "cf_handle is required before syncing contests")
    if db.session.get(OverallRating, user.id) is None:
        abort(409, "seed the ratings before replaying contests")

    try:
        history = codeforces.user_rating(user.cf_handle)
        codeforces.pace()
        submissions = codeforces.user_status(user.cf_handle)
    except codeforces.CodeforcesError as exc:
        abort(502, str(exc))

    now = datetime.now(timezone.utc)
    entered = scoring.participated_contests(submissions) | {
        row["contestId"] for row in history if row.get("contestId") is not None
    }
    catalogued = {
        contest.id: contest
        for contest in db.session.scalars(
            select(Contest).where(Contest.id.in_(entered))
        )
    } if entered else {}
    replayed = set(db.session.scalars(
        select(Problem.contest_id)
        .join(Attempt, Attempt.problem_id == Problem.id)
        .where(Attempt.user_id == user.id, Attempt.source == "contest")
        .distinct()
    ))

    contests = [contest for cid, contest in catalogued.items() if cid not in replayed]
    starts = {
        contest.id: scoring.contest_start(contest, submissions, now)
        for contest in contests
    }
    contests.sort(key=lambda contest: (starts[contest.id], contest.id))

    accepted = scoring.accepted_by_key(submissions)
    problems = skipped = solved = 0
    for contest in contests:
        result = scoring.replay_contest(user.id, contest, starts[contest.id], accepted)
        problems += result.problems
        skipped += result.skipped
        solved += result.solved
    db.session.commit()

    return {
        "replayed": len(contests),
        "already_recorded": len(set(catalogued) & replayed),
        "skipped": len(entered - set(catalogued)),  # entered but not in the catalog
        "problems": problems,
        "problems_skipped": skipped,
        "solved": solved,
    }


def _catalog_problems(keys):
    """The catalog problems matching a set of (contest id, problem index) keys."""
    contest_ids = {contest_id for contest_id, _ in keys}
    if not contest_ids:
        return []
    return [
        problem
        for problem in db.session.scalars(
            select(Problem).where(Problem.contest_id.in_(contest_ids))
        )
        if (problem.contest_id, problem.problem_index) in keys
    ]
