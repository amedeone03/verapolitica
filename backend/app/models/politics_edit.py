"""Editorial corrections to what the Politica page shows.

The official data (Governo, DAIT, camera.it, senato.it) stays as imported; a
published correction is shown in its place, with its source and reason, and
the official value stays visible next to it. Every save is a new version that
an admin publishes (or a second member, when no admin is named).
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.models.territory_block import TerritoryBlockStatus, _enum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PoliticsEdit(Base):
    __tablename__ = "politics_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    # What is corrected, e.g. "government:12", "region:3", "chamber:camera:group:7", "text:government_note".
    key: Mapped[str] = mapped_column(String(120), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[TerritoryBlockStatus] = mapped_column(
        _enum(TerritoryBlockStatus), default=TerritoryBlockStatus.PENDING, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
