from datetime import datetime

from sqlalchemy import Text, func
from sqlalchemy.orm import Mapped, mapped_column

from model.db import db
from model._common import TZ


class User(db.Model):
    """One row per person, keyed by the verified Cloudflare Access email.

    An email that verifies but has no row yet gets one on first request (see
    `routes.get_or_create_user`). `cf_handle` starts NULL and is set once
    through `PUT /api/users/me`; from then on it identifies the Codeforces
    account every CF API call is made as.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    # Nullable: a user exists before they name a Codeforces handle. Postgres
    # unique indexes ignore NULLs, so several users can be handle-less at once.
    cf_handle: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now())
