"""What the redazione did, and what it asked another member to approve.

* ``EditorialLogEntry``: one row per change made from the redazione console
  (write, edit, approve, reject, withdraw, assign a promise status). Rows are
  append-only: they cannot be updated or deleted.
* ``EditorialChangeRequest``: a change to something already public that is not
  a new draft of its own (withdrawing a published block, re-classifying a
  promise). It waits for a second member, like every other draft.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, String, Text, event
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum(enum_cls: type[StrEnum], length: int = 32) -> Enum:
    return Enum(
        enum_cls,
        values_callable=lambda item: [member.value for member in item],
        native_enum=False,
        length=length,
    )


class ImmutableEditorialLogError(RuntimeError):
    pass


class EditorialLogEntry(Base):
    __tablename__ = "editorial_log_entries"
    __table_args__ = (
        Index("ix_editorial_log_entries_created", "created_at", "id"),
        Index("ix_editorial_log_entries_object", "object_kind", "object_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor: Mapped[str] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(40), index=True)
    object_kind: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    politician_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class ChangeRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EditorialChangeRequest(Base):
    __tablename__ = "editorial_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    target_kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int] = mapped_column(Integer)
    politician_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        _enum(ChangeRequestStatus), default=ChangeRequestStatus.PENDING, index=True
    )
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


@event.listens_for(EditorialLogEntry, "before_update")
@event.listens_for(EditorialLogEntry, "before_delete")
def _log_is_append_only(_mapper: Mapper[Any], _connection: Any, _target: Any) -> None:
    raise ImmutableEditorialLogError("the editorial log is append-only")
