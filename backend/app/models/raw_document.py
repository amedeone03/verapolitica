from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.ai_extraction import AIExtractionRun, DocumentChunk
    from backend.app.models.evidence import Evidence
    from backend.app.models.identity_resolution_case import IdentityResolutionCase
    from backend.app.models.profile_draft import ProfileDraft
    from backend.app.models.parliamentary_group_membership import (
        ParliamentaryGroupMembership,
    )
    from backend.app.models.political_party_affiliation import (
        PoliticalPartyAffiliation,
    )
    from backend.app.models.proposal import (
        ProposalDraft,
        ProposalEvidence,
        ProposalStatusEvent,
    )
    from backend.app.models.territorial_office_mandate import TerritorialOfficeMandate
    from backend.app.models.territory import Municipality, Region


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RawDocumentStatus(StrEnum):
    COLLECTED = "collected"
    PARSED = "parsed"
    FAILED = "failed"


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(500))
    raw_sha256: Mapped[str] = mapped_column(String(64), index=True)
    normalized_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    structured_records: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    process_status: Mapped[RawDocumentStatus] = mapped_column(
        Enum(
            RawDocumentStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        default=RawDocumentStatus.COLLECTED,
        index=True,
    )
    change_detected: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    collector_version: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    source = relationship("Source", back_populates="raw_documents")
    profile_drafts: Mapped[list["ProfileDraft"]] = relationship(
        back_populates="raw_document"
    )
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="raw_document")
    identity_resolution_cases: Mapped[list["IdentityResolutionCase"]] = relationship(
        back_populates="raw_document"
    )
    parliamentary_group_memberships: Mapped[list["ParliamentaryGroupMembership"]] = (
        relationship(back_populates="raw_document")
    )
    political_party_affiliations: Mapped[list["PoliticalPartyAffiliation"]] = (
        relationship(back_populates="raw_document")
    )
    proposal_drafts: Mapped[list["ProposalDraft"]] = relationship(
        back_populates="raw_document"
    )
    proposal_status_events: Mapped[list["ProposalStatusEvent"]] = relationship(
        back_populates="raw_document"
    )
    proposal_evidence: Mapped[list["ProposalEvidence"]] = relationship(
        back_populates="raw_document"
    )
    document_chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="raw_document",
        cascade="all, delete-orphan",
        order_by="DocumentChunk.chunk_index",
    )
    ai_extraction_runs: Mapped[list["AIExtractionRun"]] = relationship(
        back_populates="raw_document"
    )
    regions: Mapped[list["Region"]] = relationship(back_populates="raw_document")
    municipalities: Mapped[list["Municipality"]] = relationship(
        back_populates="raw_document"
    )
    territorial_mandates: Mapped[list["TerritorialOfficeMandate"]] = relationship(
        back_populates="raw_document"
    )
