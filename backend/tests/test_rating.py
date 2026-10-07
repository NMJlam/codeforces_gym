"""The rating model is the one thing every number in the app derives from, so
it is tested against the PRD formulas written out longhand, not against itself.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from rating import (
    OVERALL_RD_CAP,
    OVERALL_RD_FLOOR,
    TOPIC_RD_CAP,
    TOPIC_RD_FLOOR,
    CalibrationFit,
    RatingState,
    aged_rd,
    calibrated_probability,
    expected_score,
    fit_calibration,
    normalised_tag_weights,
    rating_for_probability,
    update_rating,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
Q = math.log(10) / 400


def test_expected_score_is_the_prd_curve():
    assert expected_score(1500, 1500) == pytest.approx(0.5)
    # A problem 400 above the user's rating: ten times less likely than even.
    assert expected_score(1900, 1500) == pytest.approx(1 / 11)
    assert expected_score(1100, 1500) == pytest.approx(10 / 11)
    assert expected_score(1400, 1500) > expected_score(1600, 1500)


def test_multi_tag_update_matches_the_prd_formula():
    overall = RatingState(rating=1500.0, rd=200.0, last_practised_at=NOW)
    topics = {
        1: RatingState(rating=50.0, rd=100.0, last_practised_at=NOW),
        2: RatingState(rating=-30.0, rd=150.0, last_practised_at=NOW),
    }
    weights = {1: 0.75, 2: 0.25}

    update = update_rating(overall, topics, weights, problem_rating=1600, score=1, now=NOW)

    # The formulas, straight from the PRD.
    effective = 1500.0 + 0.75 * 50.0 + 0.25 * -30.0
    assert update.e_model == pytest.approx(1 / (1 + 10 ** ((1600 - effective) / 400)))
    d_square = 1 / (Q**2 * update.e_model * (1 - update.e_model))
    v = 200.0**2 + (0.75 * 100.0) ** 2 + (0.25 * 150.0) ** 2
    gain = Q * (1 - update.e_model) * d_square / (v + d_square)
    assert update.gain == pytest.approx(gain)

    assert update.overall.rating == pytest.approx(1500.0 + 200.0**2 * gain)
    assert update.topics[1].rating == pytest.approx(50.0 + 100.0**2 * 0.75 * gain)
    assert update.topics[2].rating == pytest.approx(-30.0 + 150.0**2 * 0.25 * gain)

    assert update.overall.rd == pytest.approx(math.sqrt(200.0**2 - 200.0**4 / (v + d_square)))
    assert update.topics[1].rd == pytest.approx(
        math.sqrt(100.0**2 - (100.0**2 * 0.75) ** 2 / (v + d_square))
    )


def test_multi_tag_update_is_signed_and_only_touches_named_topics():
    overall = RatingState(rating=1500.0, rd=100.0, last_practised_at=NOW)
    topics = {
        1: RatingState(rating=0.0, rd=100.0, last_practised_at=NOW),
        2: RatingState(rating=0.0, rd=100.0, last_practised_at=NOW),
    }

    solved = update_rating(overall, topics, {1: 1.0}, 1500, 1, NOW)
    failed = update_rating(overall, topics, {1: 1.0}, 1500, 0, NOW)

    assert solved.overall.rating > 1500 > failed.overall.rating
    assert solved.topics[1].rating > 0 > failed.topics[1].rating
    assert solved.overall.rd < 100  # a result always makes us more certain
    assert set(solved.topics) == {1}


def test_untouched_rating_ages_to_the_cap():
    assert aged_rd(TOPIC_RD_FLOOR, None, TOPIC_RD_CAP, NOW) == TOPIC_RD_CAP
    # 10 days of RD^2 += 10^2: sqrt(45^2 + 1000) == 55.
    ten_days_ago = NOW - timedelta(days=10)
    assert aged_rd(OVERALL_RD_FLOOR, ten_days_ago, OVERALL_RD_CAP, NOW) == pytest.approx(55.0)


def test_update_ages_rds_on_read_and_stamps_them_at_now():
    """Storing the aged RD without moving last_practised_at would age it twice."""
    stale = NOW - timedelta(days=10)
    overall = RatingState(rating=1500.0, rd=45.0, last_practised_at=stale)
    topics = {1: RatingState(rating=0.0, rd=55.0, last_practised_at=stale)}

    update = update_rating(overall, topics, {1: 1.0}, 1500, 1, NOW)

    assert update.overall.last_practised_at == NOW
    assert update.topics[1].last_practised_at == NOW
    # gain uses the RDs aged to `now` (55 and sqrt(55^2 + 1000)), not the stored 45/55.
    assert update.e_model == pytest.approx(0.5)
    d_square = 4 / Q**2
    aged_overall_rd = 55.0
    aged_topic_rd = math.sqrt(55.0**2 + 1000)
    v = aged_overall_rd**2 + aged_topic_rd**2
    gain = Q * 0.5 * d_square / (v + d_square)
    assert update.overall.rating == pytest.approx(1500.0 + aged_overall_rd**2 * gain)


def test_rds_respect_their_floors_even_when_already_at_the_floor():
    overall = RatingState(rating=1500.0, rd=OVERALL_RD_FLOOR, last_practised_at=NOW)
    topics = {1: RatingState(rating=0.0, rd=TOPIC_RD_FLOOR, last_practised_at=NOW)}

    update = update_rating(overall, topics, {1: 1.0}, 1500, 1, NOW)

    assert update.overall.rd == pytest.approx(OVERALL_RD_FLOOR)
    assert update.topics[1].rd == pytest.approx(TOPIC_RD_FLOOR)


def test_normalised_tag_weights_halve_generic_tags_and_sum_to_one():
    weights = normalised_tag_weights([(1, False), (2, True)])
    assert weights == pytest.approx({1: 0.8, 2: 0.2})

    weights = normalised_tag_weights([(1, False), (2, False), (3, True), (4, True)])
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights[1] == weights[2]
    assert weights[3] == weights[4]


def test_normalised_tag_weights_reject_an_empty_tag_sequence():
    with pytest.raises(ValueError):
        normalised_tag_weights([])


def test_no_samples_returns_the_priors_instead_of_fitting_noise():
    fit = fit_calibration([], NOW)
    assert (fit.a, fit.b, fit.n) == (0.0, 1.0, 0)
    assert calibrated_probability(0.3, fit.a, fit.b) == pytest.approx(0.3)


def test_calibration_learns_from_repeated_unexpected_successes():
    """A user who keeps beating the model's odds gets a raised chance."""
    samples = [(0.3, 1)] * 50 + [(0.3, 0)] * 5
    fit = fit_calibration(samples, NOW)

    assert fit.n == 55
    assert fit.b > 0
    assert calibrated_probability(0.3, fit.a, fit.b) > 0.3


def test_calibration_never_lets_b_go_negative():
    """Perfectly inverted predictions would want b < 0; a harder problem must
    never look easier, so the fit stays on the b > 0 side."""
    samples = [(0.9, 0)] * 40 + [(0.1, 1)] * 40
    fit = fit_calibration(samples, NOW)
    assert fit.b > 0


def test_calibration_fit_uses_the_recent_samples_more():
    """10 old misses and 30 new solves: the fit should end up optimistic."""
    samples = [(0.5, 0)] * 10 + [(0.5, 1)] * 30
    fit = fit_calibration(samples, NOW)
    assert calibrated_probability(0.5, fit.a, fit.b) > 0.5


def test_calibrated_probability_is_positive_and_monotonic():
    for expected in (0.05, 0.3, 0.5, 0.7, 0.95):
        p = calibrated_probability(expected, 0.2, 1.4)
        assert 0.0 < p < 1.0

    probs = [calibrated_probability(e, 0.2, 1.4) for e in (0.1, 0.2, 0.3, 0.4)]
    assert probs == sorted(probs)


def test_calibrated_probability_clamps_extreme_expected_values():
    # Clamping the logit input keeps an exact 0/1 E finite instead of raising.
    assert 0.0 < calibrated_probability(0.0, 0.0, 1.0) < 1e-6
    assert 1.0 > calibrated_probability(1.0, 0.0, 1.0) > 1.0 - 1e-6


@pytest.mark.parametrize("target", [0.80, 0.50, 0.25])
def test_rating_for_probability_inverts_the_calibrated_curve(target):
    a, b = 0.3, 1.6
    rating = rating_for_probability(target, effective_rating=1400, a=a, b=b)
    e = expected_score(rating, 1400)
    assert calibrated_probability(e, a, b) == pytest.approx(target)


def test_rating_for_probability_asks_for_harder_problems_at_lower_targets():
    easy, even, hard = (rating_for_probability(t, 1400, 0.3, 1.6)
                        for t in (0.80, 0.50, 0.25))
    assert easy < even < hard


def test_fit_is_a_dataclass_with_the_sample_count():
    fit = fit_calibration([(0.5, 1)], NOW)
    assert isinstance(fit, CalibrationFit)
    assert fit.n == 1 and fit.fitted_at == NOW
