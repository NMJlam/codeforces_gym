from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.db import db
from model._common import TZ, one_of

if TYPE_CHECKING:
    from model.attempt import Attempt
    from model.practice_session import PracticeSession
    from model.problem import Problem

# `recall` is the one slot that is not a fresh problem: it re-serves a problem
# the user already failed, and its attempt is never rated (see model/attempt.py).
SESSION_PICK_SLOTS = ("warmup", "main", "stretch", "recall")


class SessionPick(db.Model):
    """A problem picked for a session slot, before its timer starts.

    `Attempt` rows only exist once a problem is opened (its `started_at` is the
    timer start), so an unopened pick would otherwise be lost between the
    request that picked it and the one that opens it. This table is that
    hand-off, and nothing more: no state machine, just the four facts the
    picker needs to show it again.

    `position` is the pick's place in the session's sequence (0, 1, 2, ...) and
    is never reused, so a replacement continues the sequence even though it
    takes over the slot the replaced pick held.

    A `recall` pick is the repeat of a problem the user failed: it is built from
    a due `Revisit` instead of the picker, and its attempt is unrated. It still
    goes through this table, so a due recall survives a refresh like any other
    unopened pick.
    """

    __tablename__ = "session_picks"
    __table_args__ = (
        CheckConstraint(one_of("slot", SESSION_PICK_SLOTS), name="slot_valid"),
        CheckConstraint("position >= 0", name="position_nonneg"),
        CheckConstraint("target_probability > 0 AND target_probability < 1",
                        name="target_probability_range"),
        CheckConstraint("p_cal > 0 AND p_cal < 1", name="p_cal_range"),
        CheckConstraint("replaced_at IS NULL OR replaced_at >= picked_at",
                        name="replaced_after_picked"),
        # Stable ordering, and no two picks fighting over one place.
        UniqueConstraint("session_id", "position", name="uq_session_picks_position"),
        # The flow's invariant: at most one pick waiting to be opened.
        Index("uq_session_picks_active", "session_id", unique=True,
              postgresql_where=text("replaced_at IS NULL AND opened_attempt_id IS NULL")),
        # One attempt per pick (a replaced pick never gets one).
        Index("uq_session_picks_attempt", "opened_attempt_id", unique=True,
              postgresql_where=text("opened_attempt_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    position: Mapped[int] = mapped_column()
    slot: Mapped[str] = mapped_column(Text)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"))

    target_probability: Mapped[float] = mapped_column(Double)
    p_cal: Mapped[float] = mapped_column(Double)  # the calibrated chance at pick time
    picked_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    opened_attempt_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("attempts.id"))
    replaced_at: Mapped[datetime | None] = mapped_column(TZ)

    session: Mapped["PracticeSession"] = relationship(back_populates="picks")
    problem: Mapped["Problem"] = relationship()
    opened_attempt: Mapped["Attempt | None"] = relationship()
