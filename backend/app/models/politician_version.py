from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician import Politician
    from backend.app.models.politician_version_citation import (
        PoliticianVersionCitation,
    )
    from backend.app.models.profile_draft import ProfileDraft


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImmutablePoliticianVersionError(RuntimeError):
    pass


class PoliticianVersion(Base):
    __tablename__ = "politician_versions"
    __table_args__ = (
        UniqueConstraint(
            "politician_id",
            "version_number",
            name="uq_politician_versions_politician_version",
        ),
        CheckConstraint("version_number > 0", name="ck_version_number_positive"),
        CheckConstraint(
            "profile_schema_version > 0",
            name="ck_profile_schema_version_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="RESTRICT"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    profile_schema_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    politician: Mapped["Politician"] = relationship(
        back_populates="versions",
        foreign_keys=[politician_id],
    )
    baseline_drafts: Mapped[list["ProfileDraft"]] = relationship(
        back_populates="baseline_version",
        foreign_keys="ProfileDraft.baseline_version_id",
    )
    citations: Mapped[list["PoliticianVersionCitation"]] = relationship(
        back_populates="politician_version",
        cascade="all, delete-orphan",
        order_by="(PoliticianVersionCitation.field_path, "
        "PoliticianVersionCitation.source_name, "
        "PoliticianVersionCitation.source_url, "
        "PoliticianVersionCitation.source_field)",
    )


@event.listens_for(PoliticianVersion, "before_update")
def prevent_politician_version_update(
    mapper: Mapper[PoliticianVersion],
    connection,
    target: PoliticianVersion,
) -> None:
    del mapper, connection, target
    raise ImmutablePoliticianVersionError(
        "PoliticianVersion rows are immutable after creation"
    )
