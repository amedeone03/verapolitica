from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.identity_resolution_case import IdentityResolutionCase
    from backend.app.models.politician_source_identifier import (
        PoliticianSourceIdentifier,
    )
    from backend.app.models.raw_document import RawDocument
    from backend.app.models.parliamentary_group_membership import (
        ParliamentaryGroupMembership,
    )
    from backend.app.models.parliamentary_group_source_identifier import (
        ParliamentaryGroupSourceIdentifier,
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    raw_documents: Mapped[list["RawDocument"]] = relationship(
        back_populates="source"
    )
    politician_identifiers: Mapped[list["PoliticianSourceIdentifier"]] = relationship(
        back_populates="source"
    )
    identity_resolution_cases: Mapped[list["IdentityResolutionCase"]] = relationship(
        back_populates="source"
    )
    group_identifiers: Mapped[list["ParliamentaryGroupSourceIdentifier"]] = (
        relationship(back_populates="source")
    )
    group_memberships: Mapped[list["ParliamentaryGroupMembership"]] = relationship(
        back_populates="source"
    )
