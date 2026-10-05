from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.parliamentary_group_membership import (
        ParliamentaryGroupMembership,
    )
    from backend.app.models.parliamentary_group_source_identifier import (
        ParliamentaryGroupSourceIdentifier,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParliamentaryGroup(Base):
    """An institution- and legislature-scoped parliamentary group."""

    __tablename__ = "parliamentary_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500))
    abbreviation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    institution: Mapped[str] = mapped_column(String(200), index=True)
    legislature: Mapped[str] = mapped_column(String(50), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_identifiers: Mapped[list["ParliamentaryGroupSourceIdentifier"]] = (
        relationship(back_populates="parliamentary_group", cascade="all, delete-orphan")
    )
    memberships: Mapped[list["ParliamentaryGroupMembership"]] = relationship(
        back_populates="parliamentary_group"
    )
