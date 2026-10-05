from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.political_party import PoliticalParty
    from backend.app.models.politician import Politician
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PoliticalPartyAffiliation(Base):
    """One explicit, source-supported, time-bounded party affiliation."""

    __tablename__ = "political_party_affiliations"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "identity_key",
            name="uq_party_affiliations_source_identity_key",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    political_party_id: Mapped[int] = mapped_column(
        ForeignKey("political_parties.id", ondelete="RESTRICT"), index=True
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
    source_field: Mapped[str] = mapped_column(String(500))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    affiliation_type: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    politician: Mapped["Politician"] = relationship(
        back_populates="political_party_affiliations"
    )
    political_party: Mapped["PoliticalParty"] = relationship(
        back_populates="affiliations"
    )
    source: Mapped["Source"] = relationship(back_populates="party_affiliations")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="political_party_affiliations"
    )
