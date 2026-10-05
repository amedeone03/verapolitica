from datetime import date, datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
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
    from backend.app.models.political_party import PoliticalParty
    from backend.app.models.politician import Politician
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalType(StrEnum):
    PROPOSAL = "proposal"
    LEGISLATIVE_PROPOSAL = "legislative_proposal"
    GOVERNMENT_INITIATIVE = "government_initiative"
    EXPLICIT_PROMISE = "explicit_promise"


class ProposalStatus(StrEnum):
    ANNOUNCED = "announced"
    INTRODUCED = "introduced"
    ASSIGNED = "assigned"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ENACTED = "enacted"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"
    LAPSED = "lapsed"
    RETURNED = "returned"


class ProposalActorType(StrEnum):
    POLITICIAN = "politician"
    POLITICAL_PARTY = "political_party"
    INSTITUTION = "institution"


class ProposalActorRole(StrEnum):
    PROPOSER = "proposer"
    SPONSOR = "sponsor"
    CO_SPONSOR = "co_sponsor"
    GOVERNMENT = "government"
    COMMITMENT_OWNER = "commitment_owner"


class ProposalDraftKind(StrEnum):
    INITIAL = "initial"
    STATUS_UPDATE = "status_update"
    METADATA_UPDATE = "metadata_update"


class ProposalDraftStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ProposalReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ImmutableProposalRecordError(RuntimeError):
    pass


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_title: Mapped[str] = mapped_column(String(1000))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    exact_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_type: Mapped[ProposalType] = mapped_column(
        Enum(
            ProposalType,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=64,
        ),
        index=True,
    )
    introduced_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    current_status: Mapped[ProposalStatus | None] = mapped_column(
        Enum(
            ProposalStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=64,
        ),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_identifiers: Mapped[list["ProposalSourceIdentifier"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )
    actors: Mapped[list["ProposalActor"]] = relationship(
        back_populates="proposal", cascade="all, delete-orphan"
    )
    status_events: Mapped[list["ProposalStatusEvent"]] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalStatusEvent.effective_at, ProposalStatusEvent.id",
    )
    drafts: Mapped[list["ProposalDraft"]] = relationship(
        back_populates="proposal", order_by="ProposalDraft.created_at"
    )


class ProposalSourceIdentifier(Base):
    __tablename__ = "proposal_source_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "official_identifier", name="uq_proposal_source_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    official_identifier: Mapped[str] = mapped_column(String(1000))
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    proposal: Mapped["Proposal"] = relationship(back_populates="source_identifiers")
    source: Mapped["Source"] = relationship(back_populates="proposal_identifiers")


class ProposalActor(Base):
    __tablename__ = "proposal_actors"
    __table_args__ = (
        UniqueConstraint("proposal_id", "identity_key", name="uq_proposal_actor_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    actor_type: Mapped[ProposalActorType] = mapped_column(
        Enum(
            ProposalActorType,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    role: Mapped[ProposalActorRole] = mapped_column(
        Enum(
            ProposalActorRole,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    politician_id: Mapped[int | None] = mapped_column(
        ForeignKey("politicians.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    political_party_id: Mapped[int | None] = mapped_column(
        ForeignKey("political_parties.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    institution_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str] = mapped_column(String(500))
    source_actor_identifier: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    identity_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    proposal: Mapped["Proposal"] = relationship(back_populates="actors")
    politician: Mapped["Politician | None"] = relationship(
        back_populates="proposal_actors"
    )
    political_party: Mapped["PoliticalParty | None"] = relationship()


class ProposalStatusEvent(Base):
    __tablename__ = "proposal_status_events"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "identity_key", name="uq_proposal_status_event_key"
        ),
        Index("ix_proposal_status_events_order", "proposal_id", "effective_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="CASCADE"), index=True
    )
    normalized_status: Mapped[ProposalStatus] = mapped_column(
        Enum(
            ProposalStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=64,
        )
    )
    source_status_label: Mapped[str] = mapped_column(String(500))
    effective_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    proposal: Mapped["Proposal"] = relationship(back_populates="status_events")
    source: Mapped["Source"] = relationship(back_populates="proposal_status_events")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="proposal_status_events"
    )


class ProposalDraft(Base):
    __tablename__ = "proposal_drafts"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "observation_hash", name="uq_proposal_draft_observation"
        ),
        Index("ix_proposal_drafts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("proposals.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    baseline_status_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposal_status_events.id", ondelete="RESTRICT"), nullable=True
    )
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("proposal_drafts.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[ProposalDraftKind] = mapped_column(
        Enum(
            ProposalDraftKind,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    status: Mapped[ProposalDraftStatus] = mapped_column(
        Enum(
            ProposalDraftStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        default=ProposalDraftStatus.PENDING,
        index=True,
    )
    observation_hash: Mapped[str] = mapped_column(String(64))
    proposed_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    proposal: Mapped["Proposal"] = relationship(back_populates="drafts")
    raw_document: Mapped["RawDocument"] = relationship(back_populates="proposal_drafts")
    baseline_status_event: Mapped["ProposalStatusEvent | None"] = relationship()
    supersedes: Mapped["ProposalDraft | None"] = relationship(remote_side=[id])
    evidence: Mapped[list["ProposalEvidence"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan", order_by="ProposalEvidence.id"
    )
    review: Mapped["ProposalReview | None"] = relationship(
        back_populates="draft", uselist=False
    )


class ProposalEvidence(Base):
    __tablename__ = "proposal_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("proposal_drafts.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(500))
    source_url: Mapped[str] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(String(500))
    source_value: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped["ProposalDraft"] = relationship(back_populates="evidence")
    source: Mapped["Source"] = relationship(back_populates="proposal_evidence")
    raw_document: Mapped["RawDocument"] = relationship(back_populates="proposal_evidence")


class ProposalReview(Base):
    __tablename__ = "proposal_reviews"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_proposal_review_draft"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("proposal_drafts.id", ondelete="RESTRICT"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    decision: Mapped[ProposalReviewDecision] = mapped_column(
        Enum(
            ProposalReviewDecision,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped["ProposalDraft"] = relationship(back_populates="review")


@event.listens_for(ProposalStatusEvent, "before_update")
@event.listens_for(ProposalReview, "before_update")
def prevent_proposal_record_update(
    mapper: Mapper[Any], connection, target: object
) -> None:
    del mapper, connection, target
    raise ImmutableProposalRecordError(
        "published proposal status events and proposal reviews are immutable"
    )
