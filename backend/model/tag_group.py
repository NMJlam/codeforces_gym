from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db


class TagGroup(db.Model):
    """A dashboard radar-chart axis that tags are bucketed into (see Tag.group_id)."""

    __tablename__ = "tag_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
