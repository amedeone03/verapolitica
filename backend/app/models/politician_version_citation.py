from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Mapper, mapped_column, relationship

from backend.app.db.base import Base

if TYPE_CHECKING:
    from backend.app.models.politician_version import PoliticianVersion


class ImmutablePoliticianVersionCitationError(RuntimeError):
    pass


class PoliticianVersionCitation(Base):
    __tablename__ = "politician_version_citations"
    __table_args__ = (
        UniqueConstraint(
            "politician_version_id",
            "field_path",
            "source_name",
            "source_url",
            "source_field",
            name="uq_version_citations_public_projection",
        ),
        Index(
            "ix_version_citations_version_field",
            "politician_version_id",
            "field_path",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    politician_version_id: Mapped[int] = mapped_column(
        ForeignKey("politician_versions.id", ondelete="CASCADE"),
        index=True,
    )
    field_path: Mapped[str] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(String(500))

    politician_version: Mapped["PoliticianVersion"] = relationship(
        back_populates="citations"
    )


@event.listens_for(PoliticianVersionCitation, "before_update")
@event.listens_for(PoliticianVersionCitation, "before_delete")
def prevent_politician_version_citation_change(
    mapper: Mapper[PoliticianVersionCitation],
    connection,
    target: PoliticianVersionCitation,
) -> None:
    del mapper, connection, target
    raise ImmutablePoliticianVersionCitationError(
        "PoliticianVersionCitation rows are immutable after creation"
    )
