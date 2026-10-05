from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.models import (
    Municipality,
    ParliamentaryGroup,
    ParliamentaryGroupMembership,
    PoliticalParty,
    PoliticalPartyAffiliation,
    Politician,
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
from backend.app.services.public_proposal_service import PublicProposalQueryService


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
                    name=source.name,
                    url=membership.source_url,
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
                    name=source.name,
                    url=affiliation.source_url,
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
                        name=source.name,
                        url=mandate.source_url,
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
                        name=source.name,
                        url=mandate.source_url,
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
