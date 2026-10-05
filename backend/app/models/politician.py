from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.identity_resolution_case import IdentityResolutionCase
    from backend.app.models.politician_source_identifier import (
        PoliticianSourceIdentifier,
    )
    from backend.app.models.politician_version import PoliticianVersion
    from backend.app.models.profile_draft import ProfileDraft
    from backend.app.models.parliamentary_group_membership import (
        ParliamentaryGroupMembership,
    )
    from backend.app.models.political_party_affiliation import (
        PoliticalPartyAffiliation,
    )
    from backend.app.models.proposal import ProposalActor


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Politician(Base):
    __tablename__ = "politicians"
    __table_args__ = (
        Index("ix_politicians_normalized_name_birth_date", "normalized_name", "birth_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_given_name: Mapped[str] = mapped_column(String(200))
    canonical_family_name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(500), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "politician_versions.id",
            name="fk_politicians_current_version_id",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_identifiers: Mapped[list["PoliticianSourceIdentifier"]] = relationship(
        back_populates="politician",
        cascade="all, delete-orphan",
    )
    versions: Mapped[list["PoliticianVersion"]] = relationship(
        back_populates="politician",
        foreign_keys="PoliticianVersion.politician_id",
        order_by="PoliticianVersion.version_number",
    )
    current_version: Mapped["PoliticianVersion | None"] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )
    profile_drafts: Mapped[list["ProfileDraft"]] = relationship(
        back_populates="politician",
        order_by="ProfileDraft.created_at",
    )
    identity_resolution_cases: Mapped[list["IdentityResolutionCase"]] = relationship(
        back_populates="resolved_politician",
        foreign_keys="IdentityResolutionCase.resolved_politician_id",
    )
    parliamentary_group_memberships: Mapped[list["ParliamentaryGroupMembership"]] = (
        relationship(
            back_populates="politician",
            order_by="ParliamentaryGroupMembership.start_date",
        )
    )
    political_party_affiliations: Mapped[list["PoliticalPartyAffiliation"]] = (
        relationship(
            back_populates="politician",
            order_by="PoliticalPartyAffiliation.start_date",
        )
    )
    proposal_actors: Mapped[list["ProposalActor"]] = relationship(
        back_populates="politician"
    )
