"""Pledge fulfilment tracking ("detto / fatto").

A pledge is an approved ``Proposal`` of type ``explicit_promise``. This module
adds what the scorecard needs on top of it, following the same rules as the
rest of the domain: machines only propose, humans approve, published records
are append-only.

* ``PledgeClassification``: editorial coding of the pledge (Royed specificity,
  CPPG action/outcome type, Comparative Agendas topic, role of the owner when
  the pledge was made, mandate window). One row per proposal.
* ``PledgeAssessmentDraft`` / ``PledgeAssessmentApproval``: a proposed
  fulfilment verdict with its cited excerpt, from the evidence matcher or from
  an editor, and the reviewer approvals it collects. "Broken" needs two
  distinct reviewers.
* ``PledgeAssessment``: the immutable published verdict history. The current
  verdict is the latest row; nothing is overwritten.
* ``PledgeAuditSample`` / ``PledgeAuditCoding``: random blind re-coding with a
  recorded inclusion probability, used for agreement and for the design-based
  correction of aggregate rates.
"""

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base
from backend.app.scoring.types import (
    CommitmentType,
    EvidenceLabel,
    FulfillmentVerdict,
    HolderRole,
    PledgeSpecificity,
)

if TYPE_CHECKING:
    from backend.app.models.ai_extraction import DocumentChunk
    from backend.app.models.proposal import Proposal
    from backend.app.models.raw_document import RawDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(enum_type: type[StrEnum], length: int = 32) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda enum: [item.value for item in enum],
        native_enum=False,
        length=length,
    )


class PledgeAssessmentOrigin(StrEnum):
    EVIDENCE_MATCHER = "evidence_matcher"
    EDITOR = "editor"


class PledgeAssessmentDraftStatus(StrEnum):
    PENDING = "pending"
    AWAITING_SECOND_APPROVAL = "awaiting_second_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class ImmutablePledgeRecordError(RuntimeError):
    pass


class PledgeClassification(Base):
    __tablename__ = "pledge_classifications"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_pledge_classification_proposal"),
        CheckConstraint(
            "mandate_end IS NULL OR mandate_start IS NULL OR mandate_end >= mandate_start",
            name="ck_pledge_classification_mandate_dates",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    specificity: Mapped[PledgeSpecificity] = mapped_column(_enum(PledgeSpecificity), index=True)
    commitment_type: Mapped[CommitmentType] = mapped_column(_enum(CommitmentType))
    holder_role: Mapped[HolderRole] = mapped_column(_enum(HolderRole), index=True)
    cap_topic_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    mandate_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    mandate_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    classified_by: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    proposal: Mapped["Proposal"] = relationship()


class PledgeAssessmentDraft(Base):
    __tablename__ = "pledge_assessment_drafts"
    __table_args__ = (
        UniqueConstraint("proposal_id", "identity_key", name="uq_pledge_assessment_draft_key"),
        Index("ix_pledge_assessment_drafts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    origin: Mapped[PledgeAssessmentOrigin] = mapped_column(_enum(PledgeAssessmentOrigin))
    status: Mapped[PledgeAssessmentDraftStatus] = mapped_column(
        _enum(PledgeAssessmentDraftStatus),
        default=PledgeAssessmentDraftStatus.PENDING,
        index=True,
    )
    proposed_verdict: Mapped[FulfillmentVerdict] = mapped_column(_enum(FulfillmentVerdict))
    evidence_label: Mapped[EvidenceLabel] = mapped_column(_enum(EvidenceLabel))
    rationale: Mapped[str] = mapped_column(Text)
    quoted_excerpt: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    document_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=True
    )
    effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieval: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    judge_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    judge_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200))
    identity_key: Mapped[str] = mapped_column(String(64))
    rejection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    proposal: Mapped["Proposal"] = relationship()
    raw_document: Mapped["RawDocument"] = relationship()
    document_chunk: Mapped["DocumentChunk | None"] = relationship()
    approvals: Mapped[list["PledgeAssessmentApproval"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="PledgeAssessmentApproval.id",
    )
    assessment: Mapped["PledgeAssessment | None"] = relationship(
        back_populates="draft", uselist=False
    )


class PledgeAssessmentApproval(Base):
    __tablename__ = "pledge_assessment_approvals"
    __table_args__ = (
        UniqueConstraint("draft_id", "reviewer", name="uq_pledge_assessment_approval_reviewer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("pledge_assessment_drafts.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped["PledgeAssessmentDraft"] = relationship(back_populates="approvals")


class PledgeAssessment(Base):
    __tablename__ = "pledge_assessments"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_pledge_assessment_draft"),
        Index("ix_pledge_assessments_proposal_created", "proposal_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("pledge_assessment_drafts.id", ondelete="RESTRICT")
    )
    verdict: Mapped[FulfillmentVerdict] = mapped_column(_enum(FulfillmentVerdict), index=True)
    rationale: Mapped[str] = mapped_column(Text)
    quoted_excerpt: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_by: Mapped[list[str]] = mapped_column(JSON)
    methodology_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    proposal: Mapped["Proposal"] = relationship()
    draft: Mapped["PledgeAssessmentDraft"] = relationship(back_populates="assessment")
    raw_document: Mapped["RawDocument"] = relationship()


class PledgeAuditSample(Base):
    __tablename__ = "pledge_audit_samples"
    __table_args__ = (UniqueConstraint("sample_key", name="uq_pledge_audit_sample_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_key: Mapped[str] = mapped_column(String(100))
    seed: Mapped[int] = mapped_column(Integer)
    population_size: Mapped[int] = mapped_column(Integer)
    inclusion_probability: Mapped[float] = mapped_column(Float)
    population_ids: Mapped[list[int]] = mapped_column(JSON)
    assessment_ids: Mapped[list[int]] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    codings: Mapped[list["PledgeAuditCoding"]] = relationship(
        back_populates="sample", order_by="PledgeAuditCoding.id"
    )


class PledgeAuditCoding(Base):
    __tablename__ = "pledge_audit_codings"
    __table_args__ = (
        UniqueConstraint(
            "sample_id", "assessment_id", "coder", name="uq_pledge_audit_coding_coder"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sample_id: Mapped[int] = mapped_column(
        ForeignKey("pledge_audit_samples.id", ondelete="RESTRICT"), index=True
    )
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("pledge_assessments.id", ondelete="RESTRICT"), index=True
    )
    coder: Mapped[str] = mapped_column(String(200))
    verdict: Mapped[FulfillmentVerdict] = mapped_column(_enum(FulfillmentVerdict))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    sample: Mapped["PledgeAuditSample"] = relationship(back_populates="codings")
    assessment: Mapped["PledgeAssessment"] = relationship()


@event.listens_for(PledgeAssessment, "before_update")
@event.listens_for(PledgeAssessmentApproval, "before_update")
@event.listens_for(PledgeAuditSample, "before_update")
@event.listens_for(PledgeAuditCoding, "before_update")
def prevent_pledge_record_update(mapper: Mapper[Any], connection, target: object) -> None:
    del mapper, connection, target
    raise ImmutablePledgeRecordError(
        "published pledge assessments, approvals and audit records are immutable"
    )
