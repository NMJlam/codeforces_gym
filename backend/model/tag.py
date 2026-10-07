from sqlalchemy import CheckConstraint, Double, ForeignKey, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db


class Tag(db.Model):
    """A Codeforces tag such as "dp" or "greedy".

    is_generic tags (greedy, implementation, math, brute force, ...) get a raw
    weight of 0.25 instead of 1 before weights are normalised, so they don't
    take most of the credit for problems that are really about something else.

    group_id buckets tags for the dashboard radar chart: one axis per group,
    so every tag belongs to exactly one.

    tier_weight scales the tag's priority in the daily topic draw (1.0 = core,
    down to 0.1 = competitive-programming only).

    emergence_rating is the lowest rating bucket whose ±200-window share of
    rated problems reaches 3% — "the rating where this topic starts showing up".
    Set by POST /sync/catalog; NULL until the first sync.
    """

    __tablename__ = "tags"
    __table_args__ = (
        CheckConstraint("tier_weight > 0 AND tier_weight <= 1", name="tier_weight_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    is_generic: Mapped[bool] = mapped_column(default=False, server_default=false())
    group_id: Mapped[int | None] = mapped_column(ForeignKey("tag_groups.id"))
    tier_weight: Mapped[float] = mapped_column(Double, default=1.0, server_default=text("1.0"))
    emergence_rating: Mapped[int | None]

    @property
    def raw_weight(self) -> float:
        return 0.25 if self.is_generic else 1.0
