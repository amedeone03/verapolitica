from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician import Politician
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PoliticianSourceIdentifier(Base):
    __tablename__ = "politician_source_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "value",
            name="uq_politician_source_identifiers_source_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    value: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    politician: Mapped["Politician"] = relationship(
        back_populates="source_identifiers"
    )
    source: Mapped["Source"] = relationship(back_populates="politician_identifiers")
