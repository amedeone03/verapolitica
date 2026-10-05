from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.political_party import PoliticalParty
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PoliticalPartySourceIdentifier(Base):
    """One durable official source identity for a political party."""

    __tablename__ = "political_party_source_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "value",
            name="uq_party_source_identifiers_source_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    political_party_id: Mapped[int] = mapped_column(
        ForeignKey("political_parties.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    value: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    political_party: Mapped["PoliticalParty"] = relationship(
        back_populates="source_identifiers"
    )
    source: Mapped["Source"] = relationship(back_populates="party_identifiers")
