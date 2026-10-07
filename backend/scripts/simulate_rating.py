"""Simulation harness for the rating model (PRD: "rating engine proven in
simulation", before sessions are built on top of it).

Each simulated user has a latent overall rating and a handful of topics with
latent offsets. The harness does what picking does: choose a problem near the
user's *estimated* rating (that is all picking can see), draw the outcome from
the latent skill, and feed it through `rating.update_rating`. If the model is
sound, the estimate converges on the latent skill; the harness measures the
final absolute error and exits nonzero when the median exceeds TOLERANCE.

Deterministic: one `random.Random(seed)` drives everything.

    uv run python scripts/simulate_rating.py --seed 1 --users 100 --attempts 1000

Standard library plus the pure rating module only: no database, no Flask.
"""

import argparse
import random
import statistics
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Running this file directly puts scripts/ on sys.path, not the backend root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rating import (  # noqa: E402  (import after the path bootstrap)
    TOPIC_RD_CAP,
    RatingState,
    expected_score,
    normalised_tag_weights,
    update_rating,
)

# Documented tolerance: a converged rating should land within 100 points of the
# user's latent skill. The exit code is nonzero above this.
TOLERANCE = 100.0

START_RATING = 800.0
START_RD = 350.0
TOPICS_PER_USER = 4
TOPIC_SPREAD = 80.0        # latent per-topic offsets, symmetric around 0
PROBLEM_JITTER = 150.0     # ratings to either side of the current estimate
MIN_PROBLEM_RATING = 800
MAX_PROBLEM_RATING = 3500
ATTEMPT_INTERVAL = timedelta(hours=1)  # keeps RD aging realistic but small


def simulate_user(rng: random.Random, attempts: int) -> tuple[float, float, float]:
    """Run one user through `attempts` scored problems.

    Returns (final overall error, final mean topic-offset error, final mean
    effective-rating error). Only the last is gauge-invariant; the first is
    meaningful because the harness fixes the gauge (see below).
    """
    latent_overall = rng.uniform(1000.0, 2400.0)
    tags = list(range(TOPICS_PER_USER))
    latent_offsets = {tag: rng.gauss(0.0, TOPIC_SPREAD) for tag in tags}
    # TopicRating.rating_offset is defined relative to the overall rating, so the
    # latent offsets are zero-mean.
    shared = statistics.fmean(latent_offsets.values())
    latent_offsets = {tag: value - shared for tag, value in latent_offsets.items()}

    overall = RatingState(rating=START_RATING, rd=START_RD, last_practised_at=None)
    topics = {
        tag: RatingState(rating=0.0, rd=TOPIC_RD_CAP, last_practised_at=None)
        for tag in tags
    }
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for i in range(attempts):
        tag = tags[i % TOPICS_PER_USER]
        effective = overall.rating + topics[tag].rating
        problem_rating = int(round(
            (effective + rng.uniform(-PROBLEM_JITTER, PROBLEM_JITTER)) / 100.0
        )) * 100
        problem_rating = min(max(problem_rating, MIN_PROBLEM_RATING), MAX_PROBLEM_RATING)

        true_chance = expected_score(problem_rating, latent_overall + latent_offsets[tag])
        score = 1 if rng.random() < true_chance else 0

        update = update_rating(
            overall, topics, normalised_tag_weights([(tag, False)]),
            problem_rating, score, now,
        )
        overall, topics[tag] = update.overall, update.topics[tag]

        # Gauge fix. The attempts only ever observe `overall + offset`, so
        # shifting every offset by c and the overall by -c leaves the model's
        # likelihood untouched: the split between them is unidentifiable and
        # would otherwise random-walk into whichever value the first, largest
        # updates happened to leave it at (an error of hundreds of points with
        # no relation to estimation quality). Pinning the offsets to zero mean
        # makes "overall error" measure what it is supposed to.
        shift = statistics.fmean(t.rating for t in topics.values())
        overall = replace(overall, rating=overall.rating + shift)
        for other in tags:
            topics[other] = replace(topics[other], rating=topics[other].rating - shift)

        now += ATTEMPT_INTERVAL

    topic_error = statistics.fmean(
        abs(topics[tag].rating - latent_offsets[tag]) for tag in tags
    )
    effective_error = statistics.fmean(
        abs(overall.rating + topics[tag].rating - latent_overall - latent_offsets[tag])
        for tag in tags
    )
    return abs(overall.rating - latent_overall), topic_error, effective_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--attempts", type=int, default=1000)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    overall_errors = []
    topic_errors = []
    effective_errors = []
    for user in range(args.users):
        overall_error, topic_error, effective_error = simulate_user(rng, args.attempts)
        overall_errors.append(overall_error)
        topic_errors.append(topic_error)
        effective_errors.append(effective_error)
        print(f"user {user:>4}: overall {overall_error:7.1f}  "
              f"topic {topic_error:6.1f}  effective {effective_error:6.1f}",
              file=sys.stderr)

    overall_errors.sort()
    median = statistics.median(overall_errors)
    within = sum(1 for e in overall_errors if e <= TOLERANCE)

    print(f"\nseed={args.seed} users={args.users} attempts/user={args.attempts}")
    print(f"final overall error: median {median:.1f}  mean "
          f"{statistics.fmean(overall_errors):.1f}  p90 "
          f"{overall_errors[int(len(overall_errors) * 0.9)]:.1f}  max "
          f"{overall_errors[-1]:.1f}")
    print(f"final topic-offset error: median {statistics.median(topic_errors):.1f}")
    print(f"final effective-rating error (gauge-invariant): median "
          f"{statistics.median(effective_errors):.1f}")
    print(f"users within {TOLERANCE:.0f} points: {within}/{args.users}")

    if median > TOLERANCE:
        print(f"\nFAIL: median error {median:.1f} exceeds tolerance {TOLERANCE:.0f}")
        return 1
    print(f"\nOK: median error {median:.1f} is within tolerance {TOLERANCE:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
