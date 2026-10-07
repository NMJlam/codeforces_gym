from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    Double,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.db import db
from model._common import TZ, one_of

if TYPE_CHECKING:
    from model.attempt_tag import AttemptTag
    from model.practice_session import PracticeSession
    from model.problem import Problem

ATTEMPT_SOURCES = ("session", "self_selected", "contest")
ATTEMPT_SLOTS = ("warmup", "main", "stretch", "revisit", "recall")


class Attempt(db.Model):
    """One timed attempt. THE source of truth: everything else is rebuilt from here.

    A row is created when an attempt *starts* (problems are picked just in
    time), so a problem the user never opened is never recorded.

    Snapshots (e_model, problem_rating, effective_rating, plus attempt_tags)
    are stored at scoring time, so replays give the same numbers even if
    Codeforces later re-rates or re-tags the problem.

    A trigger freezes s, e_model, scored_at and the pause fields once the
    attempt has been scored.
    """

    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(one_of("source", ATTEMPT_SOURCES), name="source_valid"),
        CheckConstraint(f"slot IS NULL OR {one_of('slot', ATTEMPT_SLOTS)}", name="slot_valid"),
        # S is set exactly when the attempt is scored, and is 0 or 1.
        CheckConstraint("(scored_at IS NULL) = (s IS NULL)", name="scored_iff_s"),
        CheckConstraint("s IN (0, 1)", name="s_binary"),
        CheckConstraint("scored_at IS NULL OR scored_at >= started_at", name="scored_after_start"),
        # Session attempts need a session and a slot; other sources have no session.
        CheckConstraint("(source = 'session') = (session_id IS NOT NULL)", name="session_iff_source"),
        CheckConstraint("source <> 'session' OR slot IS NOT NULL", name="session_needs_slot"),
        # A solve needs an Accepted time inside the 45-minute window
        # (contests run on their own clock).
        CheckConstraint("s IS DISTINCT FROM 1 OR accepted_at IS NOT NULL", name="solve_has_accept_time"),
        CheckConstraint(
            "s IS DISTINCT FROM 1 OR source = 'contest' "
            "OR accepted_at <= started_at + interval '45 minutes'",
            name="solve_within_45_min",
        ),
        # Recall checks re-serve a seen problem, so they are never rated.
        CheckConstraint("slot IS DISTINCT FROM 'recall' OR NOT rated", name="recall_unrated"),
        # A scored, rated attempt must keep the E its update used.
        CheckConstraint("scored_at IS NULL OR NOT rated OR e_model IS NOT NULL", name="rated_has_e"),
        CheckConstraint("scored_at IS NULL OR NOT rated OR overall_after IS NOT NULL",
                        name="rated_has_overall_after"),
        CheckConstraint("e_model IS NULL OR (e_model > 0 AND e_model < 1)", name="e_model_range"),
        CheckConstraint("p_cal IS NULL OR (p_cal > 0 AND p_cal < 1)", name="p_cal_range"),
        CheckConstraint("info_factor > 0", name="info_factor_positive"),
        # Pausing only makes sense while the timer is running, and the paused
        # time only ever grows.
        CheckConstraint("paused_at IS NULL OR paused_at >= started_at", name="paused_after_start"),
        CheckConstraint("scored_at IS NULL OR paused_at IS NULL", name="paused_only_while_open"),
        CheckConstraint("paused_seconds >= 0", name="paused_seconds_nonneg"),
        # Only one open attempt per user (timer vs Done race is handled by
        # UPDATE ... WHERE scored_at IS NULL in the scoring transaction).
        Index("uq_attempts_one_open", "user_id", unique=True,
              postgresql_where=text("scored_at IS NULL")),
        # A problem is rated at most once.
        Index("uq_attempts_rated_once", "user_id", "problem_id", unique=True,
              postgresql_where=text("rated")),
        # Replay order: rated attempts by scored_at, then id.
        Index("ix_attempts_replay", "user_id", "scored_at", "id",
              postgresql_where=text("rated")),
        Index("ix_attempts_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"))

    source: Mapped[str] = mapped_column(Text)
    slot: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    scored_at: Mapped[datetime | None] = mapped_column(TZ)
    accepted_at: Mapped[datetime | None] = mapped_column(TZ)
    # CF's submission id (foreign key read straight from the CF API, no local cache).
    accepted_submission_id: Mapped[int | None] = mapped_column(BigInteger)

    # Interruption support: the timer is frozen at `paused_at` while it is set,
    # and `paused_seconds` is the total of every finished pause. The effective
    # deadline is started_at + 45 minutes + paused_seconds (see scoring).
    paused_at: Mapped[datetime | None] = mapped_column(TZ)
    paused_seconds: Mapped[int] = mapped_column(server_default=text("0"))

    s: Mapped[int | None] = mapped_column(SmallInteger)
    e_model: Mapped[float | None] = mapped_column(Double)   # E used by the update
    p_cal: Mapped[float | None] = mapped_column(Double)     # calibrated chance shown when picked
    problem_rating: Mapped[int | None]                      # snapshot
    effective_rating: Mapped[float | None] = mapped_column(Double)  # snapshot
    overall_after: Mapped[float | None] = mapped_column(Double)     # overall rating after this update (rating-over-time chart)
    info_factor: Mapped[float] = mapped_column(Double, default=1.0, server_default=text("1.0"))
    rated: Mapped[bool]

    key_idea: Mapped[str | None] = mapped_column(Text)
    upsolved_at: Mapped[datetime | None] = mapped_column(TZ)

    # Calibration only uses rated, app-picked problems.
    in_calibration: Mapped[bool] = mapped_column(
        Computed("source = 'session' AND rated", persisted=True)
    )

    session: Mapped["PracticeSession | None"] = relationship(back_populates="attempts")
    problem: Mapped["Problem"] = relationship()
    tag_weights: Mapped[list["AttemptTag"]] = relationship(back_populates="attempt")
