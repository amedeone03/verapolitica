"""Citizen accounts for the public app (follows, zone, saved posts).

These rows are not members of the redazione. A civic session cookie must not
open `/admin` or `/redazione/api`.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CivicAccount(Base):
    __tablename__ = "civic_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(40), default="")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


# The four reactions a registered reader can leave on a published post.
# Stored as short codes; the app draws them as the system emoji.
POST_REACTIONS = ("heart", "angry", "party", "tears")


class CivicPostReaction(Base):
    """One reaction per reader per post; changing it replaces the row."""

    __tablename__ = "civic_post_reactions"
    __table_args__ = (
        UniqueConstraint("account_id", "post_id", name="uq_civic_post_reactions_account_post"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("civic_accounts.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[int] = mapped_column(
        ForeignKey("editorial_posts.id", ondelete="CASCADE"), index=True
    )
    reaction: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
