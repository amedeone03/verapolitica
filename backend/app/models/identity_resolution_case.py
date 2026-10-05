from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician import Politician
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdentityResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED_EXISTING = "resolved_existing"
    RESOLVED_NEW = "resolved_new"
    IGNORED = "ignored"


class ImmutableIdentityResolutionSnapshotError(RuntimeError):
    pass


class IdentityResolutionCase(Base):
    __tablename__ = "identity_resolution_cases"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_identifier",
            name="uq_identity_resolution_cases_source_identifier",
        ),
        Index(
            "ix_identity_resolution_cases_status_created",
            "status",
            "created_at",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL "
            "AND resolved_politician_id IS NULL AND reviewer_identity IS NULL) "
            "OR (status IN ('resolved_existing', 'resolved_new') "
            "AND resolved_at IS NOT NULL AND resolved_politician_id IS NOT NULL "
            "AND reviewer_identity IS NOT NULL) "
            "OR (status = 'ignored' AND resolved_at IS NOT NULL "
            "AND resolved_politician_id IS NULL AND reviewer_identity IS NOT NULL)",
            name="ck_identity_resolution_cases_terminal_fields",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    source_identifier: Mapped[str] = mapped_column(String(1000))
    candidate_display_name: Mapped[str] = mapped_column(String(500))
    candidate_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    matching_result_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[IdentityResolutionStatus] = mapped_column(
        Enum(
            IdentityResolutionStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        default=IdentityResolutionStatus.PENDING,
        index=True,
    )
    resolved_politician_id: Mapped[int | None] = mapped_column(
        ForeignKey("politicians.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    reviewer_identity: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="identity_resolution_cases"
    )
    source: Mapped["Source"] = relationship(
        back_populates="identity_resolution_cases"
    )
    resolved_politician: Mapped["Politician | None"] = relationship(
        back_populates="identity_resolution_cases"
    )


@event.listens_for(IdentityResolutionCase, "before_update")
def prevent_identity_resolution_snapshot_update(
    mapper: Mapper[IdentityResolutionCase],
    connection,
    target: IdentityResolutionCase,
) -> None:
    del mapper, connection
    state = inspect(target)
    protected_fields = (
        "raw_document_id",
        "source_id",
        "source_identifier",
        "candidate_display_name",
        "candidate_snapshot",
        "matching_result_data",
        "created_at",
    )
    if any(state.attrs[field].history.has_changes() for field in protected_fields):
        raise ImmutableIdentityResolutionSnapshotError(
            "IdentityResolutionCase candidate snapshots are immutable"
        )
