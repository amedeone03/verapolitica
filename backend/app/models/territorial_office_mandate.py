from datetime import date, datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician import Politician
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source
    from backend.app.models.territory import Municipality, Region


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TerritorialOffice(StrEnum):
    MAYOR = "mayor"
    REGIONAL_PRESIDENT = "regional_president"


class TerritorialOfficeMandate(Base):
    """One source-supported holder interval for a territorial office."""

    __tablename__ = "territorial_office_mandates"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "identity_key",
            name="uq_territorial_mandates_source_identity_key",
        ),
        CheckConstraint(
            "(office = 'mayor' AND municipality_id IS NOT NULL AND region_id IS NULL) "
            "OR (office = 'regional_president' AND region_id IS NOT NULL "
            "AND municipality_id IS NULL)",
            name="ck_territorial_mandates_office_target",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_territorial_mandates_dates",
        ),
        Index(
            "ix_territorial_mandates_municipality_dates",
            "municipality_id",
            "start_date",
            "end_date",
        ),
        Index(
            "ix_territorial_mandates_region_dates",
            "region_id",
            "start_date",
            "end_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    office: Mapped[TerritorialOffice] = mapped_column(
        Enum(
            TerritorialOffice,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        index=True,
    )
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    municipality_id: Mapped[int | None] = mapped_column(
        ForeignKey("municipalities.id", ondelete="RESTRICT"), nullable=True, index=True
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
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    politician: Mapped["Politician"] = relationship(
        back_populates="territorial_office_mandates"
    )
    region: Mapped["Region | None"] = relationship(back_populates="mandates")
    municipality: Mapped["Municipality | None"] = relationship(
        back_populates="mandates"
    )
    source: Mapped["Source"] = relationship(back_populates="territorial_mandates")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="territorial_mandates"
    )
