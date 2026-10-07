from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ, one_of

SEEN_REASONS = ("attempted", "contest", "external", "skipped")


class SeenProblem(db.Model):
    """Problems the user must never be served as a fresh rated attempt.

    When marking a problem seen, insert a row for every problem in its
    twin_group too (Div. 1 / Div. 2 copies).
    """

    __tablename__ = "seen_problems"
    __table_args__ = (
        CheckConstraint(one_of("reason", SEEN_REASONS), name="reason_valid"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
