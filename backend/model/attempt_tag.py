from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, Double, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.db import db

if TYPE_CHECKING:
    from model.attempt import Attempt


class AttemptTag(db.Model):
    """The normalised tag weights an attempt's update actually used (a snapshot).

    Weights for one attempt sum to 1. That sum spans rows, so the app checks
    it; the DB only checks each weight's range.
    """

    __tablename__ = "attempt_tags"
    __table_args__ = (
        CheckConstraint("weight > 0 AND weight <= 1", name="weight_range"),
    )

    attempt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attempts.id"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    weight: Mapped[float] = mapped_column(Double)

    attempt: Mapped["Attempt"] = relationship(back_populates="tag_weights")
