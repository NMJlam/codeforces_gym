from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.db import db

if TYPE_CHECKING:
    from model.contest import Contest
    from model.tag import Tag


class Problem(db.Model):
    """A Codeforces problem (from problemset.problems). Catalog: safe to re-fetch.

    twin_group links a Div. 1 problem to its Div. 2 copy (parallel rounds have
    consecutive contest ids and the same problem name). Marking one as seen
    marks the whole group as seen.

    Special problems (tagged "*special") are not ingested at all, so there is
    no is_special column. There is no editorial flag either: Codeforces does
    not expose one, so the app hands the user a search string instead
    (editorial_search).
    """

    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint("contest_id", "problem_index", name="uq_problems_contest_index"),
        # Unrated problems still need a row (they can be seen in a contest).
        CheckConstraint(
            "rating IS NULL OR (rating BETWEEN 800 AND 3500 AND mod(rating, 100) = 0)",
            name="rating_valid",
        ),
        CheckConstraint("solved_count >= 0", name="solved_count_nonneg"),
        # Candidate search: "rated, within +-300 of target".
        Index(
            "ix_problems_rating_candidates",
            "rating",
            postgresql_where=text("rating IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contest_id: Mapped[int] = mapped_column(ForeignKey("contests.id"))
    problem_index: Mapped[str] = mapped_column(Text)  # "A", "B1", ...
    name: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None]
    twin_group: Mapped[int | None] = mapped_column(index=True)
    solved_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))

    contest: Mapped["Contest"] = relationship()
    tags: Mapped[list["Tag"]] = relationship(secondary="problem_tags", viewonly=True)

    @property
    def editorial_search(self) -> str:
        """Copy-paste query that finds the round's editorial.

        The contest id is not the round number (contest 1900 is Round 911), so
        this uses the contest name, which is also how Codeforces titles the
        editorial blog.
        """
        return f"{self.contest.name} editorial"
