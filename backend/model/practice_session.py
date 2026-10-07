from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.db import db
from model._common import TZ

if TYPE_CHECKING:
    from model.attempt import Attempt
    from model.session_pick import SessionPick


class PracticeSession(db.Model):
    """One practice session: today's topic plus its attempts.

    Named PracticeSession (table "sessions") so it doesn't clash with
    SQLAlchemy's own Session / db.session.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_start"),
        # Only one open session per user.
        Index(
            "uq_sessions_one_open",
            "user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))  # today's topic
    started_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(TZ)

    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="session", order_by="Attempt.started_at"
    )
    # Picked-but-unopened problems: see model/session_pick.py for why they are
    # not Attempts.
    picks: Mapped[list["SessionPick"]] = relationship(
        back_populates="session", order_by="SessionPick.position"
    )
