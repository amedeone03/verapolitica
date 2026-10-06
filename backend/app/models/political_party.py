from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.political_party_affiliation import (
        PoliticalPartyAffiliation,
    )
    from backend.app.models.political_party_source_identifier import (
        PoliticalPartySourceIdentifier,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PoliticalParty(Base):
    """A political party, kept separate from groups, lists, and coalitions."""

    __tablename__ = "political_parties"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(500))
    abbreviation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    search_primary: Mapped[str] = mapped_column(String(500), default="", index=True)
    search_document: Mapped[str] = mapped_column(Text, default="")
    official_website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str] = mapped_column(String(100), default="Italy")
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_identifiers: Mapped[list["PoliticalPartySourceIdentifier"]] = (
        relationship(back_populates="political_party", cascade="all, delete-orphan")
    )
    affiliations: Mapped[list["PoliticalPartyAffiliation"]] = relationship(
        back_populates="political_party"
    )
