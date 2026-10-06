from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models import Source
from backend.app.models.civic import (
    GeographicScopeType,
    GlossaryTerm,
    Referendum,
    ReferendumSourceIdentifier,
    ReferendumStatus,
    VotingGuide,
)
from backend.app.schemas.civic import (
    PublicGlossaryList,
    PublicGlossaryTerm,
    PublicGlossaryTermSummary,
    PublicReferendum,
    PublicReferendumList,
    PublicReferendumSource,
    PublicReferendumSummary,
    PublicVotingGuide,
    PublicVotingGuideList,
    VotingGuideSection,
)


class PublicCivicQueryService:
    """Read-only published civic records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_referendums(
        self,
        *,
        offset: int,
        limit: int,
        status: ReferendumStatus | None = None,
        scope: GeographicScopeType | None = None,
        upcoming: bool = False,
        as_of: date | None = None,
    ) -> PublicReferendumList:
        today = as_of or date.today()
        query = select(Referendum).where(Referendum.published_at.is_not(None))
        count_query = select(func.count(Referendum.id)).where(
            Referendum.published_at.is_not(None)
        )
        if status is not None:
            query = query.where(Referendum.status == status)
            count_query = count_query.where(Referendum.status == status)
        if scope is not None:
            query = query.where(Referendum.scope_type == scope)
            count_query = count_query.where(Referendum.scope_type == scope)
        if upcoming:
            query = query.where(
                func.coalesce(Referendum.vote_end_date, Referendum.vote_date) >= today
            )
            count_query = count_query.where(
                func.coalesce(Referendum.vote_end_date, Referendum.vote_date) >= today
            )
        items = list(
            self.session.scalars(
                query.options(
                    selectinload(Referendum.region),
                    selectinload(Referendum.municipality),
                )
                .order_by(Referendum.vote_date.asc(), Referendum.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        return PublicReferendumList(
            items=tuple(self._summary(item) for item in items),
            total=self.session.scalar(count_query) or 0,
            offset=offset,
            limit=limit,
        )

    def get_referendum(self, referendum_id: int) -> PublicReferendum | None:
        referendum = self.session.scalar(
            select(Referendum)
            .where(
                Referendum.id == referendum_id,
                Referendum.published_at.is_not(None),
            )
            .options(
                selectinload(Referendum.region),
                selectinload(Referendum.municipality),
                selectinload(Referendum.source_identifiers).selectinload(
                    ReferendumSourceIdentifier.source
                ),
            )
        )
        if referendum is None:
            return None
        summary = self._summary(referendum)
        return PublicReferendum(
            **summary.model_dump(),
            official_question=referendum.official_question,
            vote_end_date=referendum.vote_end_date,
            start_time=referendum.start_time,
            end_time=referendum.end_time,
            voting_hours_description=referendum.voting_hours_description,
            quorum_required=referendum.quorum_required,
            quorum_description=referendum.quorum_description,
            voting_guide_id=referendum.voting_guide_id,
            sources=tuple(
                PublicReferendumSource(
                    source_name=item.source.name,
                    official_identifier=item.official_identifier,
                    source_url=item.source_url,
                )
                for item in referendum.source_identifiers
            ),
        )

    def list_voting_guides(
        self, *, offset: int, limit: int
    ) -> PublicVotingGuideList:
        query = select(VotingGuide).where(VotingGuide.published_at.is_not(None))
        items = list(
            self.session.scalars(
                query.options(selectinload(VotingGuide.source))
                .order_by(VotingGuide.title.asc(), VotingGuide.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        total = self.session.scalar(
            select(func.count(VotingGuide.id)).where(
                VotingGuide.published_at.is_not(None)
            )
        ) or 0
        return PublicVotingGuideList(
            items=tuple(self._guide(item) for item in items),
            total=total,
            offset=offset,
            limit=limit,
        )

    def get_voting_guide(self, guide_id: int) -> PublicVotingGuide | None:
        guide = self.session.scalar(
            select(VotingGuide)
            .where(VotingGuide.id == guide_id, VotingGuide.published_at.is_not(None))
            .options(selectinload(VotingGuide.source))
        )
        if guide is None:
            return None
        return self._guide(guide)

    def list_glossary(
        self, *, offset: int, limit: int
    ) -> PublicGlossaryList:
        query = select(GlossaryTerm).where(GlossaryTerm.published_at.is_not(None))
        items = list(
            self.session.scalars(
                query.order_by(func.lower(GlossaryTerm.term).asc(), GlossaryTerm.id.asc())
                .offset(offset)
                .limit(limit)
            )
        )
        total = self.session.scalar(
            select(func.count(GlossaryTerm.id)).where(
                GlossaryTerm.published_at.is_not(None)
            )
        ) or 0
        return PublicGlossaryList(
            items=tuple(
                PublicGlossaryTermSummary(
                    slug=item.slug,
                    term=item.term,
                    short_definition=item.short_definition,
                    source_url=item.source_url,
                    extended_definition=item.extended_definition,
                )
                for item in items
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def get_glossary_term(self, slug: str) -> PublicGlossaryTerm | None:
        term = self.session.scalar(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.slug == slug.casefold(),
                GlossaryTerm.published_at.is_not(None),
            )
            .options(selectinload(GlossaryTerm.source))
        )
        if term is None:
            return None
        return PublicGlossaryTerm(
            slug=term.slug,
            term=term.term,
            short_definition=term.short_definition,
            source_url=term.source_url,
            extended_definition=term.extended_definition,
            source_name=term.source.name,
            is_synthetic=term.is_synthetic,
        )

    @staticmethod
    def _summary(referendum: Referendum) -> PublicReferendumSummary:
        return PublicReferendumSummary(
            id=referendum.id,
            title=referendum.title,
            referendum_type=referendum.referendum_type,
            status=referendum.status,
            vote_date=referendum.vote_date,
            scope_type=referendum.scope_type,
            region_name=referendum.region.canonical_name if referendum.region else None,
            municipality_name=(
                referendum.municipality.canonical_name
                if referendum.municipality
                else None
            ),
            official_source_url=referendum.official_source_url,
            is_synthetic=referendum.is_synthetic,
        )

    @staticmethod
    def _guide(guide: VotingGuide) -> PublicVotingGuide:
        return PublicVotingGuide(
            id=guide.id,
            title=guide.title,
            scope=guide.scope,
            sections=tuple(
                VotingGuideSection.model_validate(section) for section in guide.sections
            ),
            valid_from=guide.valid_from,
            valid_until=guide.valid_until,
            source_url=guide.source_url,
            source_name=guide.source.name if isinstance(guide.source, Source) else "",
            is_synthetic=guide.is_synthetic,
        )
