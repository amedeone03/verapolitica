from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.profile_draft import ProfileDraft
    from backend.app.models.raw_document import RawDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceExtractionMethod(StrEnum):
    DETERMINISTIC = "deterministic"


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_draft_field_path", "draft_id", "field_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("profile_drafts.id", ondelete="CASCADE"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(500))
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    source_record_identifier: Mapped[str] = mapped_column(Text)
    source_field_name: Mapped[str] = mapped_column(String(500))
    source_value: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[EvidenceExtractionMethod] = mapped_column(
        Enum(
            EvidenceExtractionMethod,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    draft: Mapped["ProfileDraft"] = relationship(back_populates="evidence")
    raw_document: Mapped["RawDocument"] = relationship(back_populates="evidence")
