from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    EditorialPost,
    EditorialPostStatus,
    PledgeAssessment,
    Proposal,
    ProposalActor,
    ProposalActorRole,
    Municipality,
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    PoliticalParty,
    PoliticalPartyAffiliation,
    Politician,
    PoliticianSourceIdentifier,
    PoliticianVersion,
    PoliticianVersionCitation,
    Region,
    Source,
    TerritorialOffice,
    TerritorialOfficeMandate,
)
from backend.app.schemas import (
    PublicCitation,
    PublicParliamentaryGroupMembership,
    PublicParliamentaryGroupSource,
    PublicPoliticalPartyAffiliation,
    PublicPoliticalPartySource,
    PublicPolitician,
    PublicPoliticianList,
    PublicPoliticianSummary,
    PublicTerritorialOffice,
    PublicTerritorialSource,
)
from backend.app.schemas.politician import PoliticianVersionProfile
from backend.app.schemas.public import PublicEditorialInfo, PublicPartyMark, PublicRelatedPost
from backend.app.services import symbols
from backend.app.models.politician_profile import (
    PoliticianBiography,
    PoliticianCareerEntry,
    PoliticianPosition,
    PoliticianProceeding,
    ProfileContentStatus,
)
from backend.app.services.government_offices import has_government_office
from backend.app.services.official_source_display import (
    citizen_source_label,
    citizen_source_url,
)
from backend.app.services.politician_profile_service import PoliticianProfileService
from backend.app.services.public_proposal_service import PublicProposalQueryService


class PublicPoliticianQueryService:
    """Read-only projection of explicitly published politician versions."""

    def __init__(self, session: Session, *, public_names: frozenset[str] = frozenset()) -> None:
        self.session = session
        # Only redazione members are named publicly (writer and verifier, rule 8 of
        # the writing models); operator and import identities stay internal.
        self.public_names = public_names

    def list(
        self, *, offset: int, limit: int, role: str | None = None
    ) -> PublicPoliticianList:
        visible = self._visible_query()
        if role == "governo":
            cabinet_ids = self._government_politician_ids()
            if not cabinet_ids:
                return PublicPoliticianList(
                    items=(), total=0, offset=offset, limit=limit
                )
            visible = visible.where(Politician.id.in_(cabinet_ids))
        elif role not in (None, ""):
            raise ValueError(f"unsupported politician role filter: {role!r}")
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
        parties = self.current_parties([politician.id for politician, _, _ in rows])
        return PublicPoliticianList(
            items=tuple(
                self._project_summary(politician, version, count).model_copy(
                    update={"current_party": parties.get(politician.id)}
                )
                for politician, version, count in rows
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def _government_politician_ids(self) -> tuple[int, ...]:
        return tuple(
            politician.id
            for politician, version in self.session.execute(self._visible_query())
            if has_government_office((version.profile_data or {}).get("mandates"))
        )

    def get(self, politician_id: int) -> PublicPolitician | None:
        row = self.session.execute(
            self._visible_query().where(Politician.id == politician_id)
        ).one_or_none()
        if row is None:
            return None
        politician, version = row
        identifier_hints = tuple(
            self.session.scalars(
                select(PoliticianSourceIdentifier.value).where(
                    PoliticianSourceIdentifier.politician_id == politician.id
                )
            )
        )
        citations = tuple(
            PublicCitation(
                field_path=citation.field_path,
                source_name=citizen_source_label(citation.source_name),
                source_url=citizen_source_url(
                    citation.source_url, *identifier_hints
                ),
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
        group_rows = list(
            self.session.execute(
                select(
                    ParliamentaryGroupMembership,
                    ParliamentaryGroup,
                    Source,
                )
                .join(
                    ParliamentaryGroup,
                    ParliamentaryGroup.id
                    == ParliamentaryGroupMembership.parliamentary_group_id,
                )
                .join(Source, Source.id == ParliamentaryGroupMembership.source_id)
                .where(
                    ParliamentaryGroupMembership.politician_id == politician.id
                )
            ).all()
        )
        group_rows.sort(
            key=lambda row: (
                row[0].end_date is not None,
                -(row[0].start_date.toordinal() if row[0].start_date else -1),
                row[1].institution.casefold(),
                row[1].canonical_name.casefold(),
            )
        )
        parliamentary_groups = tuple(
            PublicParliamentaryGroupMembership(
                name=group.canonical_name,
                abbreviation=group.abbreviation,
                institution=group.institution,
                legislature=group.legislature,
                start_date=membership.start_date,
                end_date=membership.end_date,
                role=membership.role,
                source=PublicParliamentaryGroupSource(
                    name=citizen_source_label(source.name),
                    url=citizen_source_url(
                        membership.source_url, membership.source_identifier
                    ),
                ),
            )
            for membership, group, source in group_rows
        )
        party_rows = list(
            self.session.execute(
                select(
                    PoliticalPartyAffiliation,
                    PoliticalParty,
                    Source,
                )
                .join(
                    PoliticalParty,
                    PoliticalParty.id
                    == PoliticalPartyAffiliation.political_party_id,
                )
                .join(Source, Source.id == PoliticalPartyAffiliation.source_id)
                .where(PoliticalPartyAffiliation.politician_id == politician.id)
            ).all()
        )
        party_rows.sort(
            key=lambda row: (
                row[0].end_date is not None,
                -(row[0].start_date.toordinal() if row[0].start_date else -1),
                row[1].canonical_name.casefold(),
            )
        )
        political_parties = tuple(
            PublicPoliticalPartyAffiliation(
                name=party.canonical_name,
                abbreviation=party.abbreviation,
                official_website_url=party.official_website_url,
                start_date=affiliation.start_date,
                end_date=affiliation.end_date,
                affiliation_type=affiliation.affiliation_type,
                source=PublicPoliticalPartySource(
                    name=citizen_source_label(source.name),
                    url=citizen_source_url(
                        affiliation.source_url, affiliation.source_identifier
                    ),
                ),
            )
            for affiliation, party, source in party_rows
        )
        return PublicPolitician(
            **summary.model_dump(),
            citations=citations,
            parliamentary_groups=parliamentary_groups,
            political_parties=political_parties,
            proposals=PublicProposalQueryService(self.session).list_for_politician(
                politician.id
            ),
            territorial_offices=self._territorial_offices(politician.id),
            biography=PoliticianProfileService.published_biography(
                self.session, politician.id
            ),
            career_entries=PoliticianProfileService.published_career_entries(
                self.session, politician.id
            ),
            positions=PoliticianProfileService.published_positions(
                self.session, politician.id
            ),
            proceedings=PoliticianProfileService.published_proceedings(
                self.session, politician.id
            ),
            editorial=self._editorial(politician.id),
        )

    def _editorial(self, politician_id: int) -> PublicEditorialInfo:
        """Who wrote and who verified what the citizen reads, and when."""

        writers: list[str] = []
        verifiers: list[str] = []
        dates = []
        for model in (PoliticianBiography, PoliticianCareerEntry, PoliticianPosition, PoliticianProceeding):
            for row in self.session.scalars(
                select(model)
                .where(model.politician_id == politician_id, model.status == ProfileContentStatus.PUBLISHED)
                .order_by(model.published_at, model.id)
            ):
                if row.created_by and row.created_by not in writers:
                    writers.append(row.created_by)
                if row.reviewed_by and row.reviewed_by not in verifiers:
                    verifiers.append(row.reviewed_by)
                if row.published_at:
                    dates.append(row.published_at)
        for assessment in self.session.scalars(
            select(PledgeAssessment)
            .join(ProposalActor, ProposalActor.proposal_id == PledgeAssessment.proposal_id)
            .where(
                ProposalActor.politician_id == politician_id,
                ProposalActor.role == ProposalActorRole.COMMITMENT_OWNER,
            )
            .order_by(PledgeAssessment.created_at)
        ):
            for name in assessment.approved_by or []:
                if name not in verifiers:
                    verifiers.append(name)
            dates.append(assessment.created_at)
        related = []
        for post in self.session.scalars(
            select(EditorialPost)
            .where(EditorialPost.status == EditorialPostStatus.PUBLISHED, EditorialPost.blocks.is_not(None))
            .order_by(EditorialPost.published_at.desc())
            .limit(300)
        ):
            if politician_id in ((post.blocks or {}).get("politician_ids") or []):
                related.append(
                    PublicRelatedPost(
                        id=post.id,
                        title=post.title,
                        published_on=post.published_at.date() if post.published_at else None,
                    )
                )
        latest = max((value.replace(tzinfo=None) for value in dates), default=None)
        return PublicEditorialInfo(
            updated_at=latest,
            written_by=tuple(name for name in writers if name in self.public_names),
            verified_by=tuple(name for name in verifiers if name in self.public_names),
            related_posts=tuple(related[:10]),
        )

    def _territorial_offices(
        self, politician_id: int
    ) -> tuple[PublicTerritorialOffice, ...]:
        mayor_rows = list(
            self.session.execute(
                select(TerritorialOfficeMandate, Municipality, Region, Source)
                .join(
                    Municipality,
                    Municipality.id == TerritorialOfficeMandate.municipality_id,
                )
                .join(Region, Region.id == Municipality.region_id)
                .join(Source, Source.id == TerritorialOfficeMandate.source_id)
                .where(
                    TerritorialOfficeMandate.politician_id == politician_id,
                    TerritorialOfficeMandate.office == TerritorialOffice.MAYOR,
                )
            )
        )
        president_rows = list(
            self.session.execute(
                select(TerritorialOfficeMandate, Region, Source)
                .join(Region, Region.id == TerritorialOfficeMandate.region_id)
                .join(Source, Source.id == TerritorialOfficeMandate.source_id)
                .where(
                    TerritorialOfficeMandate.politician_id == politician_id,
                    TerritorialOfficeMandate.office
                    == TerritorialOffice.REGIONAL_PRESIDENT,
                )
            )
        )
        offices: list[PublicTerritorialOffice] = []
        for mandate, municipality, region, source in mayor_rows:
            offices.append(
                PublicTerritorialOffice(
                    office=mandate.office.value,
                    municipality=municipality.canonical_name,
                    municipality_id=municipality.id,
                    region=region.canonical_name,
                    region_id=region.id,
                    start_date=mandate.start_date,
                    end_date=mandate.end_date,
                    source=PublicTerritorialSource(
                        name=citizen_source_label(source.name),
                        url=citizen_source_url(
                            mandate.source_url, mandate.source_identifier
                        ),
                    ),
                )
            )
        for mandate, region, source in president_rows:
            offices.append(
                PublicTerritorialOffice(
                    office=mandate.office.value,
                    region=region.canonical_name,
                    region_id=region.id,
                    start_date=mandate.start_date,
                    end_date=mandate.end_date,
                    source=PublicTerritorialSource(
                        name=citizen_source_label(source.name),
                        url=citizen_source_url(
                            mandate.source_url, mandate.source_identifier
                        ),
                    ),
                )
            )
        offices.sort(
            key=lambda item: (
                item.end_date is not None,
                -(item.start_date.toordinal()),
                item.office,
                item.municipality or "",
                item.region or "",
            )
        )
        return tuple(offices)

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

    def current_parties(self, politician_ids: "Sequence[int]") -> dict[int, PublicPartyMark]:
        """Current party of each person: an open (or not yet ended) affiliation,
        the most recent start first. People without one get no mark."""

        if not politician_ids:
            return {}
        today = date.today()
        logos = symbols.logo_urls(self.session, "party")
        rows = self.session.execute(
            select(PoliticalPartyAffiliation, PoliticalParty)
            .join(PoliticalParty, PoliticalParty.id == PoliticalPartyAffiliation.political_party_id)
            .where(PoliticalPartyAffiliation.politician_id.in_(politician_ids))
        ).all()
        rows.sort(key=lambda row: (row[0].start_date or date.min, row[0].id))
        marks: dict[int, PublicPartyMark] = {}
        for affiliation, party in rows:
            if affiliation.end_date is not None and affiliation.end_date < today:
                continue
            if affiliation.start_date is not None and affiliation.start_date > today:
                continue
            marks[affiliation.politician_id] = PublicPartyMark(
                id=party.id,
                name=party.canonical_name,
                abbreviation=party.abbreviation,
                logo_url=logos.get(str(party.id)),
            )
        return marks

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
