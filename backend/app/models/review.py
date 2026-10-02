from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.profile_draft import ProfileDraft


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ImmutableReviewError(RuntimeError):
    pass


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_reviews_draft_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("profile_drafts.id", ondelete="RESTRICT"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    decision: Mapped[ReviewDecision] = mapped_column(
        Enum(
            ReviewDecision,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        )
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    draft: Mapped["ProfileDraft"] = relationship(back_populates="review")


@event.listens_for(Review, "before_update")
def prevent_review_update(
    mapper: Mapper[Review],
    connection,
    target: Review,
) -> None:
    del mapper, connection, target
    raise ImmutableReviewError("Review rows are immutable after creation")
