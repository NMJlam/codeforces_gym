"""Topic and problem selection, as pure functions.

SQL and persistence stay in the routes: this module turns numbers that have
already been fetched into a decision, so the whole picking policy is testable
without a database and a draw can be handed a seeded `random.Random`.

Topic priority (PRD "Picking"):

    relevance * (1 + weakness + staleness/2 + uncertainty/2)

Problem score (lowest wins), over candidates within +-300 of the target:

    |P_cal - target| + 0.02 * extra technique tags + 0.03 * rarely solved
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Container, Iterable, Sequence

from rating import (
    TOPIC_RD_CAP,
    TOPIC_RD_FLOOR,
    calibrated_probability,
    expected_score,
    rating_for_probability,
)

# The three slots, easiest first: a warm-up you should mostly solve, a main
# problem at even odds, and a stretch problem you will usually miss.
TARGET_PROBABILITIES = {"warmup": 0.80, "main": 0.50, "stretch": 0.25}
SESSION_SLOTS = ("warmup", "main", "stretch")

# Eligibility: the topic must have emerged at the user's level, be a real part
# of the nearby catalogue, and still have unexplored problems to serve.
EMERGENCE_SHARE = 0.03
NEAR_WINDOW = 200
MIN_NEAR_CANDIDATES = 20

# Priority weights.
WEAKNESS_PER_100 = 1.5
STALENESS_DAYS = 30.0

# A failed problem comes back as a recall: the same problem, unrated, until it
# is solved without help. Each further failure stretches the gap, so a problem
# you keep missing slows down instead of stacking up on top of itself.
RECALL_GAPS_DAYS = (7, 21, 45, 90)

# Problems scoring.
CANDIDATE_WINDOW = 300
EXTRA_TAG_PENALTY = 0.02
RARE_SOLVE_PENALTY = 0.03
RARE_QUARTILE = 0.25

# problems.rating is constrained to this band by the schema (see model/problem.py).
# Nothing exists outside it, so a target chance under the floor can only be served
# by the easiest problems there are.
MIN_RATED = 800
MAX_RATED = 3500


@dataclass(frozen=True)
class TopicCandidate:
    """One tag as the topic draw sees it.

    `offset` is the topic rating minus the overall rating (0 for a tag that has
    never participated). `near_share` and `unseen_candidates` describe the
    catalogue within NEAR_WINDOW of the user's overall rating.
    """

    tag_id: int
    tier_weight: float
    emergence_rating: float | None
    offset: float
    rd: float
    days_since_practised: float | None
    near_share: float
    unseen_candidates: int


@dataclass(frozen=True)
class ProblemInfo:
    """A problem as the picker sees it, before any probability is computed."""

    problem_id: int
    rating: int | None
    solved_count: int
    tags: tuple[tuple[int, bool], ...]  # (tag_id, is_generic)


@dataclass(frozen=True)
class ProblemCandidate:
    problem_id: int
    rating: int
    p_cal: float
    extra_technique_tags: int
    solved_count: int


def is_eligible(topic: TopicCandidate, overall: float) -> bool:
    """Whether a topic may be drawn at all.

    Not yet emerged, too rare near the user's level, or too exhausted to have
    MIN_NEAR_CANDIDATES unseen problems are all "not yet".
    """
    if topic.emergence_rating is None or overall < topic.emergence_rating:
        return False
    if topic.near_share < EMERGENCE_SHARE:
        return False
    return topic.unseen_candidates >= MIN_NEAR_CANDIDATES


def topic_priority(topic: TopicCandidate, overall: float) -> float:
    """How much this topic deserves today's session (higher = more).

    Weakness grows only for topics rated below the overall; staleness and
    uncertainty both saturate at 1, so a never-practised topic is maximally
    stale and maximally uncertain.
    """
    weakness = max(0.0, -topic.offset / 100.0 * WEAKNESS_PER_100)
    if topic.days_since_practised is None:
        staleness = uncertainty = 1.0
    else:
        staleness = min(topic.days_since_practised / STALENESS_DAYS, 1.0)
        uncertainty = (topic.rd - TOPIC_RD_FLOOR) / (TOPIC_RD_CAP - TOPIC_RD_FLOOR)
        uncertainty = min(max(uncertainty, 0.0), 1.0)
    return topic.tier_weight * (1.0 + weakness + staleness / 2.0 + uncertainty / 2.0)


def draw_topic(topics: Iterable[TopicCandidate], overall: float,
               rng: random.Random) -> int | None:
    """Weighted random topic draw, or None when nothing is eligible."""
    pool = [topic for topic in topics if is_eligible(topic, overall)]
    if not pool:
        return None
    return rng.choices(
        [topic.tag_id for topic in pool],
        weights=[topic_priority(topic, overall) for topic in pool],
        k=1,
    )[0]


def recall_gap_days(lapses: int) -> int:
    """Days until the next recall, given how many earlier recalls were failed.

    The first repeat is a week out; every later one is further, up to the last
    entry, which then repeats for as long as the chain lasts.
    """
    return RECALL_GAPS_DAYS[min(max(lapses, 0), len(RECALL_GAPS_DAYS) - 1)]


def selectable(infos: Iterable[ProblemInfo],
               excluded: Container[int]) -> list[ProblemInfo]:
    """Drop what the user must never be served again.

    `excluded` is every problem with a seen row for this user, which already
    covers the Div. 1 / Div. 2 twin (marking a twin seen marks the group),
    externally solved problems, and problems already attempted.
    """
    return [
        info for info in infos
        if info.rating is not None and info.problem_id not in excluded
    ]


def problem_candidate(info: ProblemInfo, *, effective_rating: float, topic_tag_id: int,
                      a: float, b: float) -> ProblemCandidate:
    """Score one problem for a target probability."""
    p_cal = calibrated_probability(
        expected_score(info.rating, effective_rating), a, b,
    )
    extra = sum(
        1 for tag_id, is_generic in info.tags
        if not is_generic and tag_id != topic_tag_id
    )
    return ProblemCandidate(
        problem_id=info.problem_id,
        rating=info.rating,
        p_cal=p_cal,
        extra_technique_tags=extra,
        solved_count=info.solved_count,
    )


def rare_solve_cutoff(candidates: Sequence[ProblemCandidate]) -> float:
    """The solved_count at the bottom quartile of this candidate set.

    The bottom quartile is the lowest ceil(n/4) candidates (at least one), so
    no candidate set is ever entirely "widely solved".
    """
    counts = sorted(candidate.solved_count for candidate in candidates)
    index = max(0, math.ceil(len(counts) * RARE_QUARTILE) - 1)
    return counts[index]


def problem_cost(candidate: ProblemCandidate, target: float, rare_cutoff: float) -> float:
    cost = abs(candidate.p_cal - target) + EXTRA_TAG_PENALTY * candidate.extra_technique_tags
    if candidate.solved_count <= rare_cutoff:
        cost += RARE_SOLVE_PENALTY
    return cost


def choose_problem(candidates: Sequence[ProblemCandidate], target: float) -> ProblemCandidate | None:
    """The cheapest candidate for `target`, ties broken by problem id."""
    if not candidates:
        return None
    cutoff = rare_solve_cutoff(candidates)
    return min(
        candidates,
        key=lambda candidate: (problem_cost(candidate, target, cutoff), candidate.problem_id),
    )


def target_rating(target: float, effective_rating: float, a: float, b: float) -> float:
    """The problem rating to search around for a target calibrated chance.

    Inverting the calibrated curve is only meaningful while the curve carries
    information, and two things break it:

    * a user at the bottom of the catalogue — 80% at a rating of 620 is 200
      points below the easiest problem that exists, leaving an empty window and
      an unpickable warm-up;
    * a collapsed fit — with b near 0 (every problem looks alike) the inverse
      answers with infinity.

    So the answer is clamped to CANDIDATE_WINDOW around the user's own rating and
    then to the rated band. In the ordinary case neither clamp binds.
    """
    rating = rating_for_probability(target, effective_rating, a, b)
    near = min(max(rating, effective_rating - CANDIDATE_WINDOW),
               effective_rating + CANDIDATE_WINDOW)
    return min(max(near, MIN_RATED), MAX_RATED)


def next_slot(attempts: Sequence[tuple[str, int]]) -> str | None:
    """The slot to serve next, from the session's scored (slot, score) pairs.

    A failed warm-up earns another warm-up; a solved one promotes to main, then
    stretch, and after stretch the session is done (None).
    """
    if not attempts:
        return "warmup"
    slot, score = attempts[-1]
    if slot == "warmup":
        return "main" if score == 1 else "warmup"
    if slot == "main":
        return "stretch"
    return None
