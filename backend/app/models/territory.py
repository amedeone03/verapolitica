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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source
    from backend.app.models.territorial_office_mandate import TerritorialOfficeMandate


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TerritoryStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Region(Base):
    """An ISTAT region, identified independently of its mutable name."""

    __tablename__ = "regions"
    __table_args__ = (
        CheckConstraint(
            "length(istat_code) = 2",
            name="ck_regions_istat_code",
        ),
        CheckConstraint(
            "active_until IS NULL OR active_from IS NULL OR active_until >= active_from",
            name="ck_regions_active_dates",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    istat_code: Mapped[str] = mapped_column(String(2), unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    search_primary: Mapped[str] = mapped_column(String(500), default="", index=True)
    search_document: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TerritoryStatus] = mapped_column(
        Enum(
            TerritoryStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=16,
        ),
        default=TerritoryStatus.ACTIVE,
        index=True,
    )
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source: Mapped["Source"] = relationship(back_populates="regions")
    raw_document: Mapped["RawDocument"] = relationship(back_populates="regions")
    municipalities: Mapped[list["Municipality"]] = relationship(
        back_populates="region", order_by="Municipality.canonical_name"
    )
    mandates: Mapped[list["TerritorialOfficeMandate"]] = relationship(
        back_populates="region"
    )


class Municipality(Base):
    """An ISTAT municipality within exactly one region."""

    __tablename__ = "municipalities"
    __table_args__ = (
        CheckConstraint(
            "length(istat_code) = 6",
            name="ck_municipalities_istat_code",
        ),
        CheckConstraint(
            "length(province_abbreviation) = 2",
            name="ck_municipalities_province_abbreviation",
        ),
        CheckConstraint(
            "active_until IS NULL OR active_from IS NULL OR active_until >= active_from",
            name="ck_municipalities_active_dates",
        ),
        Index(
            "ix_municipalities_region_province_name",
            "region_id",
            "province_abbreviation",
            "canonical_name",
        ),
        Index("ix_municipalities_search_document", "search_document"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    istat_code: Mapped[str] = mapped_column(String(6), unique=True, index=True)
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    province_abbreviation: Mapped[str] = mapped_column(String(2), index=True)
    province_name: Mapped[str] = mapped_column(String(300))
    search_primary: Mapped[str] = mapped_column(String(500), default="", index=True)
    search_document: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TerritoryStatus] = mapped_column(
        Enum(
            TerritoryStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=16,
        ),
        default=TerritoryStatus.ACTIVE,
        index=True,
    )
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    region: Mapped["Region"] = relationship(back_populates="municipalities")
    source: Mapped["Source"] = relationship(back_populates="municipalities")
    raw_document: Mapped["RawDocument"] = relationship(back_populates="municipalities")
    mandates: Mapped[list["TerritorialOfficeMandate"]] = relationship(
        back_populates="municipality"
    )
