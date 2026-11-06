"""Redazione blocks for the territory schede (regione, provincia, comune).

The official base (ISTAT names, counts, office holders from the DAIT registry)
stays read-only and is always shown next to these blocks. Every save is a new
version: a pending row waits for an admin (or a second member), and publishing
it supersedes the previous published version of the same block. Nothing is
rewritten in place, so the log and the published history stay intact.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TerritoryKind(StrEnum):
    REGION = "region"
    PROVINCE = "province"
    MUNICIPALITY = "municipality"


class TerritoryBlockStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def _enum(enum_type: type[StrEnum]) -> Enum:
    return Enum(enum_type, values_callable=lambda items: [item.value for item in items], native_enum=False, length=16)


class TerritoryBlock(Base):
    __tablename__ = "territory_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    territory_kind: Mapped[TerritoryKind] = mapped_column(_enum(TerritoryKind), index=True)
    # Region id, province abbreviation or municipality id, as text.
    territory_key: Mapped[str] = mapped_column(String(16), index=True)
    block: Mapped[str] = mapped_column(String(32), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[TerritoryBlockStatus] = mapped_column(
        _enum(TerritoryBlockStatus), default=TerritoryBlockStatus.PENDING, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
