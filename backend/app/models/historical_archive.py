"""Historical archive: legislatures since 1946 and parliamentary mandates.

Legislatures are reference data (dates published by the Chambers). Historical
mandates are imported from the Chambers' open data as roster rows: they are
official records of who sat in which legislature, not full politician profiles,
so they do not go through the profile review queue. A mandate is linked to a
``Politician`` only when the official person identifier already matches a
reviewed profile.

"Prima" and "Seconda Repubblica" are a journalistic convention, not an
institutional fact, so the era is derived from the legislature number and
never stored.
"""

from datetime import date, datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Chamber(StrEnum):
    CAMERA = "camera"
    SENATO = "senato"
    COSTITUENTE = "costituente"


class HistoricalEra(StrEnum):
    COSTITUENTE = "costituente"
    PRIMA_REPUBBLICA = "prima_repubblica"
    SECONDA_REPUBBLICA = "seconda_repubblica"


ERA_LABELS = {
    HistoricalEra.COSTITUENTE: "Assemblea Costituente",
    HistoricalEra.PRIMA_REPUBBLICA: "Prima Repubblica",
    HistoricalEra.SECONDA_REPUBBLICA: "Seconda Repubblica",
}


def era_for(number: int) -> HistoricalEra:
    """0 is the Constituent Assembly; I–XI the "First", XII onwards the "Second"."""

    if number == 0:
        return HistoricalEra.COSTITUENTE
    return HistoricalEra.PRIMA_REPUBBLICA if number <= 11 else HistoricalEra.SECONDA_REPUBBLICA


class Legislature(Base):
    __tablename__ = "legislatures"
    __table_args__ = (
        CheckConstraint("number >= 0", name="ck_legislatures_number"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_legislatures_dates"
        ),
    )

    number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class HistoricalParliamentMandate(Base):
    __tablename__ = "historical_parliament_mandates"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "official_identifier", name="uq_historical_mandates_source_identifier"
        ),
        Index("ix_historical_mandates_leg_chamber", "legislature", "chamber"),
        Index("ix_historical_mandates_name", "family_name", "given_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"))
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    chamber: Mapped[Chamber] = mapped_column(
        Enum(
            Chamber,
            values_callable=lambda item: [member.value for member in item],
            native_enum=False,
            length=16,
        )
    )
    legislature: Mapped[int] = mapped_column(
        ForeignKey("legislatures.number", ondelete="RESTRICT")
    )
    official_identifier: Mapped[str] = mapped_column(String(500))
    person_identifier: Mapped[str] = mapped_column(String(500), index=True)
    given_name: Mapped[str] = mapped_column(String(200))
    family_name: Mapped[str] = mapped_column(String(200))
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    election_area: Mapped[str | None] = mapped_column(String(300), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    politician_id: Mapped[int | None] = mapped_column(
        ForeignKey("politicians.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
