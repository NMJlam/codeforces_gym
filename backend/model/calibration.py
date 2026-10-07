from datetime import datetime

from sqlalchemy import CheckConstraint, Double, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ


class Calibration(db.Model):
    """Cache: the fitted curve correction P_cal = sigma(a + b * logit(P)).

    There is no history table: the (logit(E), S) pairs are read from
    attempts WHERE in_calibration.
    """

    __tablename__ = "calibration"
    __table_args__ = (
        # b <= 0 would make a harder problem look easier.
        CheckConstraint("b > 0", name="b_positive"),
        CheckConstraint("n_attempts >= 0", name="n_attempts_nonneg"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    a: Mapped[float] = mapped_column(Double, default=0.0, server_default=text("0"))
    b: Mapped[float] = mapped_column(Double, default=1.0, server_default=text("1"))
    n_attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    fitted_at: Mapped[datetime | None] = mapped_column(TZ)
