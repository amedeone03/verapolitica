from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    Politician,
    PoliticianVersion,
    PoliticianVersionCitation,
)
from backend.app.schemas import (
    PublicCitation,
    PublicPolitician,
    PublicPoliticianList,
    PublicPoliticianSummary,
)
from backend.app.schemas.politician import PoliticianVersionProfile


class PublicPoliticianQueryService:
    """Read-only projection of explicitly published politician versions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, *, offset: int, limit: int) -> PublicPoliticianList:
        visible = self._visible_query()
        total = self.session.scalar(
            select(func.count()).select_from(visible.subquery())
        ) or 0
        citation_count = (
            select(func.count(PoliticianVersionCitation.id))
            .where(
                PoliticianVersionCitation.politician_version_id
                == PoliticianVersion.id
            )
            .correlate(PoliticianVersion)
            .scalar_subquery()
        )
        rows = self.session.execute(
            visible.add_columns(citation_count.label("citation_count")).order_by(
                func.lower(Politician.canonical_family_name),
                func.lower(Politician.canonical_given_name),
                Politician.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return PublicPoliticianList(
            items=tuple(
                self._project_summary(politician, version, count)
                for politician, version, count in rows
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def get(self, politician_id: int) -> PublicPolitician | None:
        row = self.session.execute(
            self._visible_query().where(Politician.id == politician_id)
        ).one_or_none()
        if row is None:
            return None
        politician, version = row
        citations = tuple(
            PublicCitation(
                field_path=citation.field_path,
                source_name=citation.source_name,
                source_url=citation.source_url,
                source_field=citation.source_field or None,
            )
            for citation in self.session.scalars(
                select(PoliticianVersionCitation)
                .where(
                    PoliticianVersionCitation.politician_version_id == version.id
                )
                .order_by(
                    PoliticianVersionCitation.field_path,
                    PoliticianVersionCitation.source_name,
                    PoliticianVersionCitation.source_url,
                    PoliticianVersionCitation.source_field,
                )
            )
        )
        summary = self._project_summary(politician, version, len(citations))
        return PublicPolitician(**summary.model_dump(), citations=citations)

    @staticmethod
    def _visible_query() -> Select[tuple[Politician, PoliticianVersion]]:
        return (
            select(Politician, PoliticianVersion)
            .join(
                PoliticianVersion,
                (PoliticianVersion.id == Politician.current_version_id)
                & (PoliticianVersion.politician_id == Politician.id),
            )
            .where(
                Politician.current_version_id.is_not(None),
                PoliticianVersion.published_at.is_not(None),
            )
        )

    @staticmethod
    def _project_summary(
        politician: Politician,
        version: PoliticianVersion,
        citation_count: int,
    ) -> PublicPoliticianSummary:
        profile = PoliticianVersionProfile.model_validate(version.profile_data)
        if version.published_at is None:  # narrowed by the public visibility query
            raise ValueError("published version is missing published_at")
        return PublicPoliticianSummary(
            id=politician.id,
            given_name=profile.given_name,
            family_name=profile.family_name,
            birth_date=profile.birth_date,
            current_version_number=version.version_number,
            profile_schema_version=version.profile_schema_version,
            published_at=version.published_at,
            profile=profile,
            citation_count=citation_count,
        )
