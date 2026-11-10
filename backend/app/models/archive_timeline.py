"""Editorial verification of Archivio city/region timeline drafts.

The JSON fixtures stay the source of the draft text. A published row here means
a redazione member checked that event against an official source. It never
creates a TerritorialOfficeMandate or a mayor from Wikipedia.
"""

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArchiveTimelineVerificationStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


def _enum(enum_type: type[StrEnum]) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda items: [item.value for item in items],
        native_enum=False,
        length=16,
    )


class ArchiveTimelineVerification(Base):
    __tablename__ = "archive_timeline_verifications"
    __table_args__ = (
        Index("ix_archive_timeline_verifications_slug_event", "slug", "event_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), index=True)
    event_index: Mapped[int] = mapped_column(Integer)
    official_url: Mapped[str] = mapped_column(Text)
    official_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[ArchiveTimelineVerificationStatus] = mapped_column(
        _enum(ArchiveTimelineVerificationStatus),
        default=ArchiveTimelineVerificationStatus.PENDING,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
