from datetime import datetime

from sqlalchemy import CheckConstraint, Double, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ
from rating import OVERALL_RD_CAP, OVERALL_RD_FLOOR, aged_rd


class OverallRating(db.Model):
    """Cache: the user's overall rating. Rebuilt by replaying attempts.

    rd is stored as of last_practised_at; call current_rd() for today's value.
    """

    __tablename__ = "overall_rating"
    __table_args__ = (
        CheckConstraint(
            f"rd BETWEEN {OVERALL_RD_FLOOR} AND {OVERALL_RD_CAP}", name="rd_range"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    rating: Mapped[float] = mapped_column(Double)
    rd: Mapped[float] = mapped_column(Double)
    last_practised_at: Mapped[datetime | None] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(
        TZ, server_default=func.now(), onupdate=func.now()
    )

    def current_rd(self, now: datetime | None = None) -> float:
        return aged_rd(self.rd, self.last_practised_at, OVERALL_RD_CAP, now)
