from datetime import date, datetime, time, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    Time,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.source import Source
    from backend.app.models.territory import Municipality, Region


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(enum_cls: type[StrEnum], length: int = 64):
    return Enum(
        enum_cls,
        values_callable=lambda item: [member.value for member in item],
        native_enum=False,
        length=length,
    )


class ReferendumType(StrEnum):
    NATIONAL_ABROGATIVE = "national_abrogative"
    CONSTITUTIONAL = "constitutional"
    REGIONAL = "regional"
    MUNICIPAL = "municipal"
    CONSULTATIVE = "consultative"
    OTHER = "other"


class ReferendumStatus(StrEnum):
    SCHEDULED = "scheduled"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class GeographicScopeType(StrEnum):
    NATIONAL = "national"
    REGION = "region"
    MUNICIPALITY = "municipality"


class ReferendumDraftKind(StrEnum):
    INITIAL = "initial"
    UPDATE = "update"


class ReferendumDraftStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReferendumReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class VotingGuideSectionKey(StrEnum):
    ELIGIBILITY = "eligibility"
    DATE_AND_HOURS = "date_and_hours"
    REQUIRED_DOCUMENTS = "required_documents"
    BALLOT_INSTRUCTIONS = "ballot_instructions"
    QUORUM = "quorum"
    ACCESSIBILITY = "accessibility"
    OFFICIAL_LINKS = "official_links"


class NotificationChannel(StrEnum):
    INTERNAL = "internal"


class NotificationEventType(StrEnum):
    REFERENDUM_UPCOMING = "referendum_upcoming"
    VOTING_DAY_REMINDER = "voting_day_reminder"


class ImmutableCivicRecordError(RuntimeError):
    pass


class Referendum(Base):
    __tablename__ = "referendums"
    __table_args__ = (
        CheckConstraint(
            "("
            "(scope_type = 'national' AND region_id IS NULL AND municipality_id IS NULL) OR "
            "(scope_type = 'region' AND region_id IS NOT NULL AND municipality_id IS NULL) OR "
            "(scope_type = 'municipality' AND municipality_id IS NOT NULL)"
            ")",
            name="ck_referendums_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(1000))
    official_question: Mapped[str] = mapped_column(Text)
    referendum_type: Mapped[ReferendumType] = mapped_column(
        _enum(ReferendumType), index=True
    )
    status: Mapped[ReferendumStatus] = mapped_column(
        _enum(ReferendumStatus), index=True
    )
    vote_date: Mapped[date] = mapped_column(Date, index=True)
    vote_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    voting_hours_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_type: Mapped[GeographicScopeType] = mapped_column(
        _enum(GeographicScopeType), index=True
    )
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    municipality_id: Mapped[int | None] = mapped_column(
        ForeignKey("municipalities.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    quorum_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quorum_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    official_source_url: Mapped[str] = mapped_column(Text)
    voting_guide_id: Mapped[int | None] = mapped_column(
        ForeignKey("voting_guides.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    search_primary: Mapped[str] = mapped_column(String(500), default="", index=True)
    search_document: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_identifiers: Mapped[list["ReferendumSourceIdentifier"]] = relationship(
        back_populates="referendum", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["ReferendumDraft"]] = relationship(
        back_populates="referendum", order_by="ReferendumDraft.created_at"
    )
    region: Mapped["Region | None"] = relationship()
    municipality: Mapped["Municipality | None"] = relationship()
    voting_guide: Mapped["VotingGuide | None"] = relationship()


class ReferendumSourceIdentifier(Base):
    __tablename__ = "referendum_source_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "official_identifier", name="uq_referendum_source_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referendum_id: Mapped[int] = mapped_column(
        ForeignKey("referendums.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    official_identifier: Mapped[str] = mapped_column(String(1000))
    source_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    referendum: Mapped["Referendum"] = relationship(back_populates="source_identifiers")
    source: Mapped["Source"] = relationship(back_populates="referendum_identifiers")


class ReferendumDraft(Base):
    __tablename__ = "referendum_drafts"
    __table_args__ = (
        UniqueConstraint(
            "referendum_id", "observation_hash", name="uq_referendum_draft_observation"
        ),
        Index("ix_referendum_drafts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    referendum_id: Mapped[int] = mapped_column(
        ForeignKey("referendums.id", ondelete="RESTRICT"), index=True
    )
    raw_document_id: Mapped[int] = mapped_column(
        ForeignKey("raw_documents.id", ondelete="RESTRICT"), index=True
    )
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("referendum_drafts.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[ReferendumDraftKind] = mapped_column(_enum(ReferendumDraftKind, 32))
    status: Mapped[ReferendumDraftStatus] = mapped_column(
        _enum(ReferendumDraftStatus, 32),
        default=ReferendumDraftStatus.PENDING,
        index=True,
    )
    observation_hash: Mapped[str] = mapped_column(String(64))
    proposed_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    referendum: Mapped["Referendum"] = relationship(back_populates="drafts")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="referendum_drafts"
    )
    supersedes: Mapped["ReferendumDraft | None"] = relationship(remote_side=[id])
    evidence: Mapped[list["ReferendumEvidence"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="ReferendumEvidence.id",
    )
    review: Mapped["ReferendumReview | None"] = relationship(
        back_populates="draft", uselist=False
    )


class ReferendumEvidence(Base):
    __tablename__ = "referendum_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("referendum_drafts.id", ondelete="CASCADE"), index=True
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

    draft: Mapped["ReferendumDraft"] = relationship(back_populates="evidence")
    source: Mapped["Source"] = relationship(back_populates="referendum_evidence")
    raw_document: Mapped["RawDocument"] = relationship(
        back_populates="referendum_evidence"
    )


class ReferendumReview(Base):
    __tablename__ = "referendum_reviews"
    __table_args__ = (UniqueConstraint("draft_id", name="uq_referendum_review_draft"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("referendum_drafts.id", ondelete="RESTRICT"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    decision: Mapped[ReferendumReviewDecision] = mapped_column(
        _enum(ReferendumReviewDecision, 32)
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped["ReferendumDraft"] = relationship(back_populates="review")


class VotingGuide(Base):
    __tablename__ = "voting_guides"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    scope: Mapped[GeographicScopeType] = mapped_column(_enum(GeographicScopeType))
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source: Mapped["Source"] = relationship(back_populates="voting_guides")


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    term: Mapped[str] = mapped_column(String(300), index=True)
    short_definition: Mapped[str] = mapped_column(Text)
    extended_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    search_primary: Mapped[str] = mapped_column(String(500), default="", index=True)
    search_document: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source: Mapped["Source"] = relationship(back_populates="glossary_terms")


class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "destination_token",
            "event_type",
            "referendum_id",
            name="uq_notification_subscription_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[NotificationChannel] = mapped_column(
        _enum(NotificationChannel, 32), default=NotificationChannel.INTERNAL
    )
    destination_token: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[NotificationEventType] = mapped_column(
        _enum(NotificationEventType)
    )
    referendum_id: Mapped[int | None] = mapped_column(
        ForeignKey("referendums.id", ondelete="CASCADE"), nullable=True, index=True
    )
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    municipality_id: Mapped[int | None] = mapped_column(
        ForeignKey("municipalities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    referendum: Mapped["Referendum | None"] = relationship()
    region: Mapped["Region | None"] = relationship()
    municipality: Mapped["Municipality | None"] = relationship()


class NotificationReminderCandidate(Base):
    __tablename__ = "notification_reminder_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[NotificationEventType] = mapped_column(
        _enum(NotificationEventType), index=True
    )
    referendum_id: Mapped[int] = mapped_column(
        ForeignKey("referendums.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    referendum: Mapped["Referendum"] = relationship()


@event.listens_for(ReferendumReview, "before_update")
def prevent_civic_review_update(
    mapper: Mapper[Any], connection, target: object
) -> None:
    del mapper, connection, target
    raise ImmutableCivicRecordError("referendum reviews are immutable")
