from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.parliamentary_group import ParliamentaryGroup
    from backend.app.models.source import Source


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ParliamentaryGroupSourceIdentifier(Base):
    """Official group identity, scoped because some URIs span legislatures."""

    __tablename__ = "parliamentary_group_source_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "value",
            "legislature",
            name="uq_group_source_identifiers_source_value_legislature",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parliamentary_group_id: Mapped[int] = mapped_column(
        ForeignKey("parliamentary_groups.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), index=True
    )
    value: Mapped[str] = mapped_column(String(1000))
    legislature: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    parliamentary_group: Mapped["ParliamentaryGroup"] = relationship(
        back_populates="source_identifiers"
    )
    source: Mapped["Source"] = relationship(back_populates="group_identifiers")
