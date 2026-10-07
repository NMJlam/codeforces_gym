from datetime import datetime

from sqlalchemy import CheckConstraint, Double, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ
from rating import TOPIC_RD_CAP, TOPIC_RD_FLOOR, aged_rd


class TopicRating(db.Model):
    """Cache: the user's offset for one topic (topic rating = overall + offset).

    The column is rating_offset, not offset: OFFSET is a reserved word in
    Postgres and would need quoting in every raw SQL query.
    """

    __tablename__ = "topic_ratings"
    __table_args__ = (
        CheckConstraint(f"rd BETWEEN {TOPIC_RD_FLOOR} AND {TOPIC_RD_CAP}", name="rd_range"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
    rating_offset: Mapped[float] = mapped_column(Double, default=0.0)
    rd: Mapped[float] = mapped_column(Double, default=TOPIC_RD_CAP)
    last_practised_at: Mapped[datetime | None] = mapped_column(TZ)
    updated_at: Mapped[datetime] = mapped_column(
        TZ, server_default=func.now(), onupdate=func.now()
    )

    def current_rd(self, now: datetime | None = None) -> float:
        return aged_rd(self.rd, self.last_practised_at, TOPIC_RD_CAP, now)
