from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.proposal import ProposalDraft
    from backend.app.models.raw_document import RawDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AIExtractionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AIExtractionCandidateStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ABSTAINED = "abstained"
    DUPLICATE = "duplicate"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "raw_document_id", "chunk_index", name="uq_document_chunk_index"
        ),
        Index("ix_document_chunks_document_hash", "raw_document_id", "chunk_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    raw_document: Mapped["RawDocument"] = relationship(back_populates="document_chunks")
    candidate_evidence: Mapped[list["AIExtractionCandidateEvidence"]] = relationship(
        back_populates="chunk"
    )


class AIExtractionRun(Base):
    __tablename__ = "ai_extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "completed_idempotency_key", name="uq_ai_extraction_completed_key"
        ),
        Index("ix_ai_extraction_run_document_created", "raw_document_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[AIExtractionRunStatus] = mapped_column(
        Enum(
            AIExtractionRunStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), index=True)
    completed_idempotency_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    input_chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    output_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    abstained_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    request_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_response: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON, nullable=True
    )
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="ai_extraction_runs"
    )
    candidates: Mapped[list["AIExtractionCandidate"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AIExtractionCandidate.id"
    )


class AIExtractionCandidate(Base):
    __tablename__ = "ai_extraction_candidates"
    __table_args__ = (
        UniqueConstraint("run_id", "candidate_index", name="uq_ai_candidate_index"),
        Index("ix_ai_candidate_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_extraction_runs.id", ondelete="CASCADE"), index=True
    )
    candidate_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[AIExtractionCandidateStatus] = mapped_column(
        Enum(
            AIExtractionCandidateStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        index=True,
    )
    deduplication_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_output: Mapped[dict[str, Any]] = mapped_column(JSON)
    observation_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposal_drafts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["AIExtractionRun"] = relationship(back_populates="candidates")
    proposal_draft: Mapped["ProposalDraft | None"] = relationship()
    evidence: Mapped[list["AIExtractionCandidateEvidence"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="AIExtractionCandidateEvidence.id",
    )


class AIExtractionCandidateEvidence(Base):
    __tablename__ = "ai_extraction_candidate_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("ai_extraction_candidates.id", ondelete="CASCADE"), index=True
    )
    document_chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), index=True
    )
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supporting_text: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    candidate: Mapped["AIExtractionCandidate"] = relationship(back_populates="evidence")
    chunk: Mapped["DocumentChunk"] = relationship(back_populates="candidate_evidence")
