"""The picker decides what the user practises, so its rules are pinned here
without a database: eligibility, priority, exclusions, the target ordering and
the warm-up flow.
"""

import math
import random

import pytest

from picking import (
    EMERGENCE_SHARE,
    MIN_NEAR_CANDIDATES,
    ProblemCandidate,
    ProblemInfo,
    TopicCandidate,
    choose_problem,
    draw_topic,
    is_eligible,
    next_slot,
    problem_candidate,
    rare_solve_cutoff,
    recall_gap_days,
    selectable,
    topic_priority,
)
from rating import calibrated_probability, expected_score


def topic(**overrides) -> TopicCandidate:
    fields = dict(
        tag_id=1, tier_weight=1.0, emergence_rating=1000.0, offset=-150.0, rd=150.0,
        days_since_practised=30.0, near_share=0.05, unseen_candidates=25,
    )
    return TopicCandidate(**{**fields, **overrides})


def test_topic_priority_is_the_prd_formula():
    # weakness 1.5 per 100 points below the overall, staleness and uncertainty
    # both saturated at 1.
    assert topic_priority(topic(), overall=2000) == pytest.approx(
        1.0 * (1 + 150 / 100 * 1.5 + 1 / 2 + 1 / 2)
    )


def test_topic_priority_ignores_an_offset_above_the_overall():
    """A topic the user is already better at is not a weakness."""
    assert topic(offset=250.0) and topic_priority(topic(offset=250.0), 2000) == pytest.approx(
        1.0 * (1 + 0 + 1 / 2 + 1 / 2)
    )


def test_topic_priority_scales_with_half_saturated_staleness_and_uncertainty():
    # 15 days: staleness 0.5. rd 102.5 is exactly halfway between floor and cap.
    priority = topic_priority(topic(offset=50.0, days_since_practised=15.0, rd=102.5), 2000)
    assert priority == pytest.approx(1.0 * (1 + 0 + 0.25 + 0.25))


def test_untouched_topic_counts_as_maximally_stale_and_uncertain():
    untouched = topic(offset=0.0, days_since_practised=None, rd=150.0)
    assert topic_priority(untouched, 2000) == pytest.approx(1.0 * (1 + 0 + 0.5 + 0.5))


def test_topic_priority_follows_the_tier_weight():
    assert topic_priority(topic(tier_weight=0.5), 2000) == pytest.approx(
        0.5 * topic_priority(topic(tier_weight=1.0), 2000)
    )


def test_eligibility_requires_emergence_nearby_share_and_unseen_candidates():
    assert is_eligible(topic(), overall=2000)

    # Below the emergence rating: the topic is above the user's level.
    assert not is_eligible(topic(emergence_rating=2100.0), overall=2000)
    # Never emerged in the catalogue at all.
    assert not is_eligible(topic(emergence_rating=None), overall=3000)
    # Too rare nearby.
    assert not is_eligible(topic(near_share=EMERGENCE_SHARE / 2), overall=2000)
    # Not enough left to serve.
    assert not is_eligible(topic(unseen_candidates=MIN_NEAR_CANDIDATES - 1), overall=2000)


def test_draw_topic_ignores_ineligible_topics_and_can_find_none():
    assert draw_topic([topic(), topic(tag_id=2, emergence_rating=4000)], 2000,
                      random.Random(0)) == 1
    assert draw_topic([], 2000, random.Random(0)) is None
    assert draw_topic([topic(emergence_rating=4000)], 2000, random.Random(0)) is None


def test_draw_topic_weights_by_priority():
    weak = topic(tag_id=10, offset=-300.0, rd=150.0, days_since_practised=30.0)   # priority 1+4.5+1=6.5
    strong = topic(tag_id=11, offset=300.0, rd=55.0, days_since_practised=0.0)    # priority 1+0+0=1
    rng = random.Random(7)
    picks = [draw_topic([weak, strong], 2000, rng) for _ in range(2000)]
    assert picks.count(10) > picks.count(11) * 3


def test_selectable_drops_unrated_and_seen_problems():
    infos = [
        ProblemInfo(problem_id=1, rating=1500, solved_count=10, tags=((1, False),)),
        ProblemInfo(problem_id=2, rating=None, solved_count=10, tags=((1, False),)),   # unrated
        ProblemInfo(problem_id=3, rating=1500, solved_count=10, tags=((1, False),)),   # seen
        ProblemInfo(problem_id=4, rating=1600, solved_count=10, tags=((1, False),)),   # twin was seen
    ]
    # The caller passes every seen problem id; mark_seen writes one row per twin,
    # so a problem whose Div. 1 copy was seen is excluded by its own id.
    left = selectable(infos, excluded={3, 4})
    assert [info.problem_id for info in left] == [1]


def test_problem_candidate_counts_only_extra_technique_tags():
    info = ProblemInfo(
        problem_id=5, rating=1500, solved_count=42,
        tags=((1, False), (2, True), (3, False), (4, False)),
    )
    candidate = problem_candidate(info, effective_rating=1400, topic_tag_id=1, a=0.0, b=1.0)

    assert candidate.extra_technique_tags == 2  # tags 3 and 4; tag 2 is generic
    assert candidate.p_cal == pytest.approx(calibrated_probability(
        expected_score(1500, 1400), 0.0, 1.0))


def candidates(*ratings_and_counts) -> list[ProblemCandidate]:
    return [
        ProblemCandidate(problem_id=problem_id, rating=rating,
                         p_cal=expected_score(rating, 1500), extra_technique_tags=0,
                         solved_count=solved_count)
        for problem_id, rating, solved_count in ratings_and_counts
    ]


def test_choose_problem_takes_the_closest_calibrated_chance():
    pool = candidates((1, 1300, 500), (2, 1480, 500), (3, 1700, 500))
    assert choose_problem(pool, 0.50).problem_id == 2


def test_choose_problem_breaks_ties_by_problem_id():
    pool = candidates((9, 1500, 100), (4, 1500, 100))
    assert choose_problem(pool, 0.50).problem_id == 4


def test_choose_problem_prefers_a_widely_solved_problem_all_else_equal():
    """The rarely-solved penalty makes the bottom quartile cost 0.03 more."""
    pool = candidates((1, 1500, 5), (2, 1500, 900), (3, 1500, 900), (4, 1500, 900))
    assert choose_problem(pool, 0.50).problem_id == 2


def test_choose_problem_asks_for_harder_problems_at_lower_targets():
    pool = candidates(*[(problem_id, 1000 + 200 * problem_id, 500) for problem_id in range(8)])
    chosen = {target: choose_problem(pool, target).rating
              for target in (0.80, 0.50, 0.25)}
    assert chosen[0.80] < chosen[0.50] < chosen[0.25]


def test_choose_problem_with_no_candidates_is_none():
    assert choose_problem([], 0.5) is None


def test_rare_solve_cutoff_is_the_bottom_quartile():
    pool = candidates(*[(i, 1500, count) for i, count in enumerate([1, 2, 3, 4, 100])])
    assert rare_solve_cutoff(pool) == 2  # counts[int(5 * 0.25)]


def test_next_slot_promotes_only_after_a_solved_warmup():
    assert next_slot([]) == "warmup"
    assert next_slot([("warmup", 1)]) == "main"
    assert next_slot([("warmup", 0)]) == "warmup"
    assert next_slot([("warmup", 0), ("warmup", 0), ("warmup", 1)]) == "main"
    assert next_slot([("warmup", 1), ("main", 0)]) == "stretch"
    assert next_slot([("warmup", 1), ("main", 1), ("stretch", 1)]) is None


def test_target_rating_clamps_to_the_rated_band():
    """A user at 620 cannot have an 80% problem 200 points below: the catalogue
    starts at 800, so the warm-up is served by the easiest problems there are."""
    from picking import MIN_RATED, target_rating

    assert target_rating(0.80, effective_rating=620.0, a=0.0, b=1.0) == MIN_RATED


def test_target_rating_survives_a_collapsed_fit():
    """With b near 0 the inverse of the curve is infinite; it must stay rated."""
    from picking import MAX_RATED, MIN_RATED, target_rating

    for target in (0.80, 0.50, 0.25):
        for b in (0.001, 0.01, 0.2):
            rating = target_rating(target, 900.0, 0.0, b)
            assert math.isfinite(rating)
            assert MIN_RATED <= rating <= MAX_RATED


def test_target_rating_is_unchanged_where_the_curve_works():
    """The clamp must not move an ordinary target: 80% at 1500 stays 202 below."""
    from picking import target_rating
    from rating import rating_for_probability

    plain = rating_for_probability(0.80, 1500.0, 0.0, 1.0)
    assert 800 < plain < 3500
    assert target_rating(0.80, 1500.0, 0.0, 1.0) == plain


def test_the_recall_gap_stretches_and_then_stops_growing():
    """A repeat comes back in a week, later each time it is failed again."""
    assert recall_gap_days(0) == 7
    assert recall_gap_days(1) == 21
    assert recall_gap_days(2) == 45
    assert recall_gap_days(3) == 90
    # It keeps coming back, at the widest gap, for as long as it is failed.
    assert recall_gap_days(9) == 90
    assert all(recall_gap_days(n) <= recall_gap_days(n + 1) for n in range(12))
