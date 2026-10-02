from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.evidence import Evidence
    from backend.app.models.politician import Politician
    from backend.app.models.politician_version import PoliticianVersion
    from backend.app.models.raw_document import RawDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProfileDraftKind(StrEnum):
    INITIAL = "initial"
    UPDATE = "update"


class ProfileDraftStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ProfileDraft(Base):
    __tablename__ = "profile_drafts"
    __table_args__ = (
        Index("ix_profile_drafts_politician_status", "politician_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_id: Mapped[int] = mapped_column(
        ForeignKey("politicians.id", ondelete="RESTRICT"), index=True
    )
    baseline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("politician_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("profile_drafts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    kind: Mapped[ProfileDraftKind] = mapped_column(
        Enum(
            ProfileDraftKind,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    status: Mapped[ProfileDraftStatus] = mapped_column(
        Enum(
            ProfileDraftStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        default=ProfileDraftStatus.PENDING,
        index=True,
    )
    profile_schema_version: Mapped[int] = mapped_column(Integer, default=1)
    proposed_profile_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    diff_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    politician: Mapped["Politician"] = relationship(back_populates="profile_drafts")
    baseline_version: Mapped["PoliticianVersion | None"] = relationship(
        back_populates="baseline_drafts",
        foreign_keys=[baseline_version_id],
    )
    raw_document: Mapped["RawDocument"] = relationship(back_populates="profile_drafts")
    supersedes: Mapped["ProfileDraft | None"] = relationship(
        remote_side=[id],
        foreign_keys=[supersedes_id],
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="Evidence.id",
    )
