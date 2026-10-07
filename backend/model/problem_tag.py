from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db


class ProblemTag(db.Model):
    """Which tags a problem has (many-to-many). Catalog: safe to re-fetch."""

    __tablename__ = "problem_tags"
    __table_args__ = (
        # The PK covers lookups by problem; this covers "all problems with tag X".
        Index("ix_problem_tags_tag_problem", "tag_id", "problem_id"),
    )

    problem_id: Mapped[int] = mapped_column(
        ForeignKey("problems.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
