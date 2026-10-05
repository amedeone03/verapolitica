from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.parliamentary_group import ParliamentaryGroup
    from backend.app.models.politician import Politician
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParliamentaryGroupMembership(Base):
    """One source-reported, time-bounded group membership or role interval."""

    __tablename__ = "parliamentary_group_memberships"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "identity_key",
            name="uq_group_memberships_source_identity_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    parliamentary_group_id: Mapped[int] = mapped_column(
        ForeignKey("parliamentary_groups.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    identity_key: Mapped[str] = mapped_column(String(64))
    source_identifier: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    role: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    politician: Mapped["Politician"] = relationship(
        back_populates="parliamentary_group_memberships"
    )
    parliamentary_group: Mapped["ParliamentaryGroup"] = relationship(
        back_populates="memberships"
    )
    source: Mapped["Source"] = relationship(back_populates="group_memberships")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="parliamentary_group_memberships"
    )
