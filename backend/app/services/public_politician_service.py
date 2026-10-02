from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models import Politician, PoliticianVersion
from backend.app.schemas import PublicPolitician, PublicPoliticianList
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
        rows = self.session.execute(
            visible.order_by(
                func.lower(Politician.canonical_family_name),
                func.lower(Politician.canonical_given_name),
                Politician.id,
            )
            .offset(offset)
            .limit(limit)
        ).all()
        return PublicPoliticianList(
            items=tuple(self._project(politician, version) for politician, version in rows),
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
        return self._project(*row)

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
    def _project(
        politician: Politician,
        version: PoliticianVersion,
    ) -> PublicPolitician:
        profile = PoliticianVersionProfile.model_validate(version.profile_data)
        if version.published_at is None:  # narrowed by the public visibility query
            raise ValueError("published version is missing published_at")
        return PublicPolitician(
            id=politician.id,
            given_name=profile.given_name,
            family_name=profile.family_name,
            birth_date=profile.birth_date,
            current_version_number=version.version_number,
            profile_schema_version=version.profile_schema_version,
            published_at=version.published_at,
            profile=profile,
        )
