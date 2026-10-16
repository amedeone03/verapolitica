"""Editorially reviewed politician narrative extras.

Biography, historical career rows, evidence-backed positions and
proceedings/controversies are generic profile content. They are not inferred
at publication time, they are not Meloni-specific, and unpublished rows are
never public. Published rows are not rewritten in place: a replacement is a
new pending record that supersedes the previous published one.
"""

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician import Politician
    from backend.app.models.politician_version import PoliticianVersion


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(enum_cls: type[StrEnum], length: int = 64):
    return Enum(
        enum_cls,
        values_callable=lambda item: [member.value for member in item],
        native_enum=False,
        length=length,
    )


class ProfileContentStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProfileSourceKind(StrEnum):
    OFFICIAL = "official"
    INSTITUTIONAL = "institutional"
    NEWS = "news"
    PARTY_POLITICIAN = "party_politician"
    FACT_CHECK = "fact_check"
    OTHER = "other"


class ProfileContentKind(StrEnum):
    BIOGRAPHY = "biography"
    CAREER_ENTRY = "career_entry"
    POSITION = "position"
    PROCEEDING = "proceeding"


class DatePrecision(StrEnum):
    YEAR = "year"
    MONTH = "month"
    DAY = "day"


class ProceedingType(StrEnum):
    JUDICIAL_PROCEEDING = "judicial_proceeding"
    INVESTIGATION = "investigation"
    POLITICAL_CONTROVERSY = "political_controversy"
    LEGAL_CONTROVERSY = "legal_controversy"
    MEDIA_CONTROVERSY = "media_controversy"


class ProceedingOutcome(StrEnum):
    ARCHIVED = "archived"
    ONGOING = "ongoing"
    DISMISSED = "dismissed"
    UNKNOWN = "unknown"


class ImmutableProfileContentError(RuntimeError):
    pass


class _ProfileContentMixin:
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="CASCADE"), index=True
    )
    politician_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("politician_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    identity_key: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[ProfileContentStatus] = mapped_column(
        _enum(ProfileContentStatus, 32),
        default=ProfileContentStatus.PENDING,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class PoliticianBiography(Base, _ProfileContentMixin):
    __tablename__ = "politician_biographies"
    __table_args__ = (
        Index(
            "ix_politician_biographies_identity",
            "politician_id",
            "identity_key",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)

    politician: Mapped["Politician"] = relationship(back_populates="biographies")
    politician_version: Mapped["PoliticianVersion | None"] = relationship()


class PoliticianCareerEntry(Base, _ProfileContentMixin):
    __tablename__ = "politician_career_entries"
    __table_args__ = (
        Index(
            "ix_politician_career_entries_identity",
            "politician_id",
            "identity_key",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_precision: Mapped[DatePrecision] = mapped_column(
        _enum(DatePrecision, 16), default=DatePrecision.YEAR
    )
    end_precision: Mapped[DatePrecision | None] = mapped_column(
        _enum(DatePrecision, 16), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(500))
    institution: Mapped[str] = mapped_column(String(500))
    organization: Mapped[str | None] = mapped_column(String(500), nullable=True)
    party_or_group: Mapped[str | None] = mapped_column(String(500), nullable=True)

    politician: Mapped["Politician"] = relationship(back_populates="career_entries")
    politician_version: Mapped["PoliticianVersion | None"] = relationship()


class PoliticianPosition(Base, _ProfileContentMixin):
    __tablename__ = "politician_positions"
    __table_args__ = (
        Index(
            "ix_politician_positions_identity",
            "politician_id",
            "identity_key",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(200))
    position_statement: Mapped[str] = mapped_column(Text)
    verifiable_statement: Mapped[str] = mapped_column(Text)
    statement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    statement_precision: Mapped[DatePrecision | None] = mapped_column(
        _enum(DatePrecision, 16), nullable=True
    )

    politician: Mapped["Politician"] = relationship(back_populates="positions")
    politician_version: Mapped["PoliticianVersion | None"] = relationship()


class PoliticianProceeding(Base, _ProfileContentMixin):
    __tablename__ = "politician_proceedings"
    __table_args__ = (
        Index(
            "ix_politician_proceedings_identity",
            "politician_id",
            "identity_key",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    proceeding_types: Mapped[list[str]] = mapped_column(JSON)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_precision: Mapped[DatePrecision | None] = mapped_column(
        _enum(DatePrecision, 16), nullable=True
    )
    outcome: Mapped[ProceedingOutcome | None] = mapped_column(
        _enum(ProceedingOutcome, 32), nullable=True
    )
    outcome_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    outcome_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    politician: Mapped["Politician"] = relationship(back_populates="proceedings")
    politician_version: Mapped["PoliticianVersion | None"] = relationship()


class PoliticianProfileSource(Base):
    __tablename__ = "politician_profile_sources"
    __table_args__ = (
        Index(
            "ix_politician_profile_sources_content",
            "content_kind",
            "content_id",
            "sort_index",
        ),
        UniqueConstraint(
            "content_kind",
            "content_id",
            "sort_index",
            name="uq_politician_profile_source_slot",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_kind: Mapped[ProfileContentKind] = mapped_column(
        _enum(ProfileContentKind, 32), index=True
    )
    content_id: Mapped[int] = mapped_column(index=True)
    sort_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[ProfileSourceKind] = mapped_column(_enum(ProfileSourceKind, 32))
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    incomplete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


def _freeze_published_profile_content(
    mapper: Mapper[Any], connection: Any, target: Any
) -> None:
    del mapper, connection
    if target.published_at is None:
        return
    if getattr(target, "status", None) is ProfileContentStatus.SUPERSEDED:
        return
    raise ImmutableProfileContentError("published profile content cannot be rewritten")


event.listen(PoliticianBiography, "before_delete", _freeze_published_profile_content)
event.listen(PoliticianCareerEntry, "before_delete", _freeze_published_profile_content)
event.listen(PoliticianPosition, "before_delete", _freeze_published_profile_content)
event.listen(PoliticianProceeding, "before_delete", _freeze_published_profile_content)
