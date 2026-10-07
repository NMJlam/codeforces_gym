from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ, one_of

REVISIT_KINDS = ("related", "recall")
REVISIT_STATUSES = ("pending", "served", "cancelled")


class Revisit(db.Model):
    """A follow-up queued when an attempt is failed.

    related: an unseen problem with matching tags at a similar rating (rated),
             queued 2-4 weeks out.
    recall:  the original problem, served again unrated, and re-queued with a
             longer gap every time it is failed, until it is solved first try.
    """

    __tablename__ = "revisits"
    __table_args__ = (
        CheckConstraint(one_of("kind", REVISIT_KINDS), name="kind_valid"),
        CheckConstraint(one_of("status", REVISIT_STATUSES), name="status_valid"),
        CheckConstraint(
            "status <> 'served' OR served_attempt_id IS NOT NULL", name="served_has_attempt"
        ),
        # A failure can't queue the same kind of revisit twice.
        UniqueConstraint("source_attempt_id", "kind", name="uq_revisits_source_kind"),
        # "What's due today?"
        Index("ix_revisits_due", "user_id", "due_on",
              postgresql_where=text("status = 'pending'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_attempt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("attempts.id"))
    kind: Mapped[str] = mapped_column(Text)
    due_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    served_attempt_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("attempts.id"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
