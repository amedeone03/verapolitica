"""Newsroom posts for the home feed ("carica la redazione").

A post is a short, sourced civic update, not an opinion column. It is written
as a draft, needs an approval from someone other than its author, and is
immutable once published. A correction is a new post that points at the post it
corrects, so the published record never changes silently.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    event,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(enum_cls: type[StrEnum], length: int = 32):
    return Enum(
        enum_cls,
        values_callable=lambda item: [member.value for member in item],
        native_enum=False,
        length=length,
    )


class FeedScope(StrEnum):
    NATIONAL = "national"
    REGION = "region"
    PROVINCE = "province"
    MUNICIPALITY = "municipality"


class EditorialPostStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ImmutableEditorialPostError(RuntimeError):
    pass


class EditorialPost(Base):
    __tablename__ = "editorial_posts"
    __table_args__ = (
        CheckConstraint(
            "(scope <> 'region' OR region_id IS NOT NULL)"
            " AND (scope <> 'province' OR province_abbreviation IS NOT NULL)"
            " AND (scope <> 'municipality' OR municipality_id IS NOT NULL)",
            name="ck_editorial_posts_scope_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    scope: Mapped[FeedScope] = mapped_column(_enum(FeedScope), index=True)
    region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    province_abbreviation: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    municipality_id: Mapped[int | None] = mapped_column(
        ForeignKey("municipalities.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    # Structured "Modello Notizia" blocks written in the redazione console.
    blocks: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    corrects_id: Mapped[int | None] = mapped_column(
        ForeignKey("editorial_posts.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[EditorialPostStatus] = mapped_column(
        _enum(EditorialPostStatus), default=EditorialPostStatus.PENDING, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200))
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


_FROZEN_AFTER_PUBLICATION = (
    "title",
    "body",
    "scope",
    "region_id",
    "province_abbreviation",
    "municipality_id",
    "citations",
    "blocks",
    "corrects_id",
    "status",
    "published_at",
)


@event.listens_for(EditorialPost, "before_update")
def _published_posts_are_immutable(
    _mapper: Mapper, connection, target: EditorialPost
) -> None:
    previous = connection.execute(
        EditorialPost.__table__.select().where(EditorialPost.__table__.c.id == target.id)
    ).mappings().first()
    if previous is None or previous["status"] != EditorialPostStatus.PUBLISHED.value:
        return
    for name in _FROZEN_AFTER_PUBLICATION:
        current = getattr(target, name)
        current = current.value if isinstance(current, StrEnum) else current
        old = previous[name]
        if isinstance(old, datetime) and isinstance(current, datetime):
            changed = old.replace(tzinfo=None) != current.replace(tzinfo=None)
        else:
            changed = old != current
        if changed:
            raise ImmutableEditorialPostError(
                "published posts cannot change; publish a correction instead"
            )


@event.listens_for(EditorialPost, "before_delete")
def _published_posts_are_not_deleted(_mapper: Mapper, _connection, target: EditorialPost) -> None:
    if target.status is EditorialPostStatus.PUBLISHED:
        raise ImmutableEditorialPostError("published posts cannot be deleted")
