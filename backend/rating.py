"""The rating model, as pure functions over immutable dataclasses.

No ORM, no Flask, no network: everything here is a deterministic function of
its arguments, so the model can be unit tested and simulated
(`scripts/simulate_rating.py`) without a database. Persistence lives in the
route layer, which snapshots these results into `overall_rating`,
`topic_ratings`, `calibration` and `attempts`.

Formulas (PRD "Rating model"):

    q       = ln(10) / 400
    E       = 1 / (1 + 10^((problem - effective) / 400))
    P_cal   = sigma(a + b * logit(E))          (picking only)
    d^2     = 1 / (q^2 * E * (1 - E))
    V       = RD_o^2 + sum_t w_t^2 RD_t^2
    gain    = q (S - E) d^2 / (V + d^2)
    overall += RD_o^2 * gain
    offset_t+= RD_t^2 * w_t * gain
    RD^2    -= (RD^2 w)^2 / (V + d^2)

`effective` is the user's rating for the problem at hand: the overall rating
plus the weighted average of the selected tags' offsets. RDs are aged on read
(never written back), so an update takes the *stored* RDs and the current time
and returns RDs stamped at that time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

Q = math.log(10) / 400.0

# RD aging: RD^2 += 10^2 per day since last practised (PRD: RD aging on read).
RD_GROWTH_PER_DAY = 10.0

# RD bounds: the caps are also the "no data yet" RD of an untouched rating.
OVERALL_RD_FLOOR = 45.0
OVERALL_RD_CAP = 350.0
TOPIC_RD_FLOOR = 55.0
TOPIC_RD_CAP = 150.0

# A generic tag (greedy, implementation, math, ...) carries a quarter of the
# weight of a specific one before normalisation (PRD: tag weights).
GENERIC_RAW_WEIGHT = 0.25
SPECIFIC_RAW_WEIGHT = 1.0

# Calibration priors: a = 0 +/- 0.5, b = 1 +/- 0.5 with b > 0.
PRIOR_A_MEAN = 0.0
PRIOR_A_SD = 0.5
PRIOR_B_MEAN = 1.0
PRIOR_B_SD = 0.5

CALIBRATION_HALF_LIFE = 100.0  # attempts; the newest sample weighs 1.0

# A brand-new user: 800 +/- 350 (the RD cap).
NEW_USER_RATING = 800.0
# Codeforces under-rates a fresh account, so the PRD adds back whatever is left
# of a newcomer bonus after 1..5 rated contests (+0 from the sixth on).
NEWCOMER_BONUS = {1: 900.0, 2: 550.0, 3: 300.0, 4: 150.0, 5: 50.0}

_FIT_MAX_ITERATIONS = 50
_FIT_TOLERANCE = 1e-8
_MIN_STEP = 1e-6
_LOGIT_EPS = 1e-9


@dataclass(frozen=True)
class RatingState:
    """A rating and its RD as stored at `last_practised_at`.

    For a topic, `rating` is the offset from the overall rating (topic rating =
    overall + offset). `last_practised_at=None` means "never practised": the RD
    is the cap and nothing ages it down.
    """

    rating: float
    rd: float
    last_practised_at: datetime | None = None


@dataclass(frozen=True)
class RatingUpdate:
    """What one scored attempt does to the user's rating.

    `topics` holds only the tags that participated; a tag seen for the first
    time enters here with offset 0 (its caller decides the starting RD).
    """

    e_model: float
    gain: float
    overall: RatingState
    topics: Mapping[int, RatingState]


@dataclass(frozen=True)
class CalibrationFit:
    """MAP fit of P_cal = sigma(a + b * logit(E)) over `n` weighted samples."""

    a: float
    b: float
    n: int
    fitted_at: datetime | None = None


def aged_rd(rd: float, last_practised_at: datetime | None, cap: float,
            now: datetime | None = None) -> float:
    """RD as it stands *now* (PRD: aging on read, never written back).

    The stored RD is the value at last practice. Writing the aged value back
    without moving `last_practised_at` would age it twice, so callers only
    ever read this.
    """
    if last_practised_at is None:
        return cap
    now = now or datetime.now(last_practised_at.tzinfo)
    days = max((now - last_practised_at).total_seconds() / 86400.0, 0.0)
    return min(cap, math.sqrt(rd * rd + RD_GROWTH_PER_DAY ** 2 * days))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def logit(p: float) -> float:
    p = min(max(p, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return math.log(p / (1.0 - p))


def expected_score(problem_rating: float, effective_rating: float) -> float:
    """E: the model's chance the user solves a problem of that rating."""
    return 1.0 / (1.0 + 10.0 ** ((problem_rating - effective_rating) / 400.0))


def calibrated_probability(expected: float, a: float, b: float) -> float:
    """P_cal: the correction from the user's own history, used only for picking.

    Only the logit input is clamped, so an E of exactly 0 or 1 (a huge rating
    gap) cannot produce an infinite logit.
    """
    return sigmoid(a + b * logit(expected))


def rating_for_probability(target: float, effective_rating: float, a: float,
                           b: float) -> float:
    """Inverse of E -> P_cal: the problem rating whose calibrated chance is `target`.

    Used by picking to turn "80% / 50% / 25%" into a rating to search around.
    A collapsed fit (b near 0, where every problem looks alike) saturates the
    sigmoid at exactly 0 or 1, and the inverse has no finite answer there; the
    result is clamped away from the ends so this stays total and the caller can
    bound the rating it actually searches (see picking.target_rating).
    """
    e = sigmoid((logit(target) - a) / b)
    e = min(max(e, _LOGIT_EPS), 1.0 - _LOGIT_EPS)
    return effective_rating + 400.0 * math.log10((1.0 - e) / e)


def initial_overall_rating(contest_rating: float | None, contests_played: int) -> float:
    """The seeded starting overall rating (PRD "New user").

    With no contest history it is the 800 new-user prior. Otherwise it is the
    handle's current Codeforces rating plus what is left of the newcomer bonus,
    so a fresh account is not seeded far below its real strength.
    """
    if contest_rating is None or contests_played <= 0:
        return NEW_USER_RATING
    return float(contest_rating) + NEWCOMER_BONUS.get(contests_played, 0.0)


def normalised_tag_weights(tags: Sequence[tuple[int, bool]]) -> dict[int, float]:
    """(tag_id, is_generic) pairs -> weights summing to 1.

    Rejects an empty sequence: a rated update with no technique evidence would
    move the overall rating while crediting nothing, which the model has no way
    to interpret.
    """
    if not tags:
        raise ValueError("a rated update needs at least one tag")
    raw = {
        tag_id: GENERIC_RAW_WEIGHT if is_generic else SPECIFIC_RAW_WEIGHT
        for tag_id, is_generic in tags
    }
    total = sum(raw.values())
    return {tag_id: weight / total for tag_id, weight in raw.items()}


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _rd_from_square(rd_square: float, floor: float, cap: float) -> float:
    return _clamp(math.sqrt(max(rd_square, 0.0)), floor, cap)


def update_rating(overall: RatingState, topics: Mapping[int, RatingState],
                  weights: Mapping[int, float], problem_rating: float,
                  score: int, now: datetime) -> RatingUpdate:
    """Apply one scored attempt and return the new overall/topic states.

    RDs are aged to `now` first, so passing the stored states is enough; the
    result's RDs are stamped `last_practised_at=now` and must be stored as-is.
    """
    if not weights:
        raise ValueError("a rated update needs at least one tag")

    o_rd = aged_rd(overall.rd, overall.last_practised_at, OVERALL_RD_CAP, now)
    t_rds = {
        tag_id: aged_rd(topics[tag_id].rd, topics[tag_id].last_practised_at,
                        TOPIC_RD_CAP, now)
        for tag_id in weights
    }

    offset = sum(w * topics[tag_id].rating for tag_id, w in weights.items())
    e = expected_score(problem_rating, overall.rating + offset)

    d_square = 1.0 / (Q ** 2 * e * (1.0 - e))
    v = o_rd ** 2 + sum((w * t_rds[tag_id]) ** 2 for tag_id, w in weights.items())
    gain = Q * (score - e) * d_square / (v + d_square)

    new_topics = {}
    for tag_id, w in weights.items():
        rd_square = t_rds[tag_id] ** 2
        new_topics[tag_id] = RatingState(
            rating=topics[tag_id].rating + rd_square * w * gain,
            rd=_rd_from_square(
                rd_square - (rd_square * w) ** 2 / (v + d_square),
                TOPIC_RD_FLOOR, TOPIC_RD_CAP,
            ),
            last_practised_at=now,
        )

    o_rd_square = o_rd ** 2
    return RatingUpdate(
        e_model=e,
        gain=gain,
        overall=RatingState(
            rating=overall.rating + o_rd_square * gain,
            rd=_rd_from_square(
                o_rd_square - o_rd_square ** 2 / (v + d_square),
                OVERALL_RD_FLOOR, OVERALL_RD_CAP,
            ),
            last_practised_at=now,
        ),
        topics=new_topics,
    )


def calibration_weights(n: int) -> list[float]:
    """Sample weights, newest first: 1.0, then half every 100 attempts back."""
    return [0.5 ** (ago / CALIBRATION_HALF_LIFE) for ago in range(n)]


def _log_posterior(a: float, b: float, xs: list[float], ss: list[float],
                   ws: list[float]) -> float:
    """Weighted log likelihood plus the Gaussian priors on a and b."""
    total = (-0.5 * (a - PRIOR_A_MEAN) ** 2 / PRIOR_A_SD ** 2
             - 0.5 * (b - PRIOR_B_MEAN) ** 2 / PRIOR_B_SD ** 2)
    for x, s, w in zip(xs, ss, ws):
        p = _clamp(sigmoid(a + b * x), _LOGIT_EPS, 1.0 - _LOGIT_EPS)
        total += w * (s * math.log(p) + (1.0 - s) * math.log(1.0 - p))
    return total


def fit_calibration(samples: Sequence[tuple[float, int]],
                    now: datetime | None = None) -> CalibrationFit:
    """Fit (a, b) by MAP Newton iteration. `samples` is (E, S) oldest first.

    An empty history returns the priors rather than fitting noise, and b is
    constrained to stay positive (a harder problem must never look easier).
    """
    n = len(samples)
    if n == 0:
        return CalibrationFit(PRIOR_A_MEAN, PRIOR_B_MEAN, 0, now)

    xs = [logit(e) for e, _ in samples]
    ss = [float(s) for _, s in samples]
    ws = list(reversed(calibration_weights(n)))  # oldest first

    lam_a = 1.0 / PRIOR_A_SD ** 2
    lam_b = 1.0 / PRIOR_B_SD ** 2
    a, b = PRIOR_A_MEAN, PRIOR_B_MEAN

    for _ in range(_FIT_MAX_ITERATIONS):
        # Gradient and Hessian of the log posterior (the Hessian is negative
        # definite, so Newton moves toward the maximum).
        grad_a = -lam_a * (a - PRIOR_A_MEAN)
        grad_b = -lam_b * (b - PRIOR_B_MEAN)
        h_aa, h_ab, h_bb = -lam_a, 0.0, -lam_b
        for x, s, w in zip(xs, ss, ws):
            p = sigmoid(a + b * x)
            residual = w * (s - p)
            curvature = w * p * (1.0 - p)
            grad_a += residual
            grad_b += residual * x
            h_aa -= curvature
            h_ab -= curvature * x
            h_bb -= curvature * x * x

        det = h_aa * h_bb - h_ab * h_ab
        if det <= 0.0:
            break
        # Maximising a concave function: the step is -H^-1 g (H is negative
        # definite, so this is an ascent direction).
        step_a = -(h_bb * grad_a - h_ab * grad_b) / det
        step_b = -(h_aa * grad_b - h_ab * grad_a) / det

        current = _log_posterior(a, b, xs, ss, ws)
        scale = 1.0
        while scale > _MIN_STEP:
            next_a, next_b = a + scale * step_a, b + scale * step_b
            if next_b > 0.0 and _log_posterior(next_a, next_b, xs, ss, ws) >= current:
                break
            scale /= 2.0
        else:
            break  # no step in this direction improves on the current point

        a, b = a + scale * step_a, b + scale * step_b
        if max(abs(scale * step_a), abs(scale * step_b)) < _FIT_TOLERANCE:
            break

    return CalibrationFit(a, b, n, now)
