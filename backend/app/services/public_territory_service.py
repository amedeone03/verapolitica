from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.models import (
    Municipality,
    Politician,
    PoliticianVersion,
    Region,
    TerritorialOffice,
    TerritorialOfficeMandate,
)
from backend.app.schemas import (
    PublicMunicipality,
    PublicMunicipalityList,
    PublicMunicipalitySummary,
    PublicOfficeHolder,
    PublicRegion,
    PublicRegionList,
    PublicRegionSummary,
    PublicTerritorialSource,
)


class PublicTerritoryQueryService:
    """Read-only paginated projection of regions, municipalities, and current holders."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_regions(self, *, offset: int, limit: int) -> PublicRegionList:
        total = self.session.scalar(select(func.count()).select_from(Region)) or 0
        regions = list(
            self.session.scalars(
                select(Region)
                .order_by(func.lower(Region.canonical_name), Region.istat_code)
                .offset(offset)
                .limit(limit)
            )
        )
        presidents = self._current_holders(
            TerritorialOffice.REGIONAL_PRESIDENT,
            region_ids=tuple(region.id for region in regions),
        )
        return PublicRegionList(
            items=tuple(
                self._region_summary(region, presidents.get(region.id))
                for region in regions
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def get_region(self, region_id: int) -> PublicRegion | None:
        region = self.session.scalar(
            select(Region)
            .options(joinedload(Region.source))
            .where(Region.id == region_id)
        )
        if region is None:
            return None
        president = self._current_holders(
            TerritorialOffice.REGIONAL_PRESIDENT, region_ids=(region.id,)
        ).get(region.id)
        municipality_count = self.session.scalar(
            select(func.count())
            .select_from(Municipality)
            .where(Municipality.region_id == region.id)
        ) or 0
        return PublicRegion(
            **self._region_summary(region, president).model_dump(),
            municipality_count=municipality_count,
            source=self._source(region),
        )

    def list_municipalities(
        self,
        *,
        offset: int,
        limit: int,
        region_id: int | None = None,
    ) -> PublicMunicipalityList:
        query: Select[tuple[Municipality, Region]] = select(Municipality, Region).join(
            Region, Region.id == Municipality.region_id
        )
        count_query = select(func.count()).select_from(Municipality)
        if region_id is not None:
            query = query.where(Municipality.region_id == region_id)
            count_query = count_query.where(Municipality.region_id == region_id)
        total = self.session.scalar(count_query) or 0
        rows = list(
            self.session.execute(
                query.order_by(
                    func.lower(Region.canonical_name),
                    func.lower(Municipality.canonical_name),
                    Municipality.istat_code,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        mayors = self._current_holders(
            TerritorialOffice.MAYOR,
            municipality_ids=tuple(municipality.id for municipality, _ in rows),
        )
        return PublicMunicipalityList(
            items=tuple(
                self._municipality_summary(
                    municipality, region, mayors.get(municipality.id)
                )
                for municipality, region in rows
            ),
            total=total,
            offset=offset,
            limit=limit,
        )

    def get_municipality(self, municipality_id: int) -> PublicMunicipality | None:
        row = self.session.execute(
            select(Municipality, Region)
            .join(Region, Region.id == Municipality.region_id)
            .options(joinedload(Municipality.source))
            .where(Municipality.id == municipality_id)
        ).one_or_none()
        if row is None:
            return None
        municipality, region = row
        mayor = self._current_holders(
            TerritorialOffice.MAYOR, municipality_ids=(municipality.id,)
        ).get(municipality.id)
        return PublicMunicipality(
            **self._municipality_summary(municipality, region, mayor).model_dump(),
            province_name=municipality.province_name,
            source=self._source(municipality),
        )

    def _current_holders(
        self,
        office: TerritorialOffice,
        *,
        municipality_ids: Iterable[int] | None = None,
        region_ids: Iterable[int] | None = None,
    ) -> dict[int, PublicOfficeHolder]:
        ids = tuple(municipality_ids or region_ids or ())
        if not ids:
            return {}
        query = (
            select(TerritorialOfficeMandate, Politician)
            .join(Politician, Politician.id == TerritorialOfficeMandate.politician_id)
            .where(
                TerritorialOfficeMandate.office == office,
                TerritorialOfficeMandate.end_date.is_(None),
            )
        )
        if municipality_ids is not None:
            query = query.where(TerritorialOfficeMandate.municipality_id.in_(ids))
        else:
            query = query.where(TerritorialOfficeMandate.region_id.in_(ids))
        published_ids = set(
            self.session.scalars(
                select(Politician.id)
                .join(
                    PoliticianVersion,
                    PoliticianVersion.id == Politician.current_version_id,
                )
                .where(PoliticianVersion.published_at.is_not(None))
            )
        )
        holders: dict[int, tuple[TerritorialOfficeMandate, Politician]] = {}
        for mandate, politician in self.session.execute(query):
            territory_id = (
                mandate.municipality_id
                if office is TerritorialOffice.MAYOR
                else mandate.region_id
            )
            if territory_id is None:
                continue
            current = holders.get(territory_id)
            if current is None or mandate.start_date > current[0].start_date:
                holders[territory_id] = (mandate, politician)
        return {
            territory_id: PublicOfficeHolder(
                politician_id=(
                    politician.id if politician.id in published_ids else None
                ),
                given_name=politician.canonical_given_name,
                family_name=politician.canonical_family_name,
                start_date=mandate.start_date,
            )
            for territory_id, (mandate, politician) in holders.items()
        }

    @staticmethod
    def _region_summary(
        region: Region, president: PublicOfficeHolder | None
    ) -> PublicRegionSummary:
        return PublicRegionSummary(
            id=region.id,
            istat_code=region.istat_code,
            name=region.canonical_name,
            status=region.status.value,
            current_president=president,
        )

    @staticmethod
    def _municipality_summary(
        municipality: Municipality,
        region: Region,
        mayor: PublicOfficeHolder | None,
    ) -> PublicMunicipalitySummary:
        return PublicMunicipalitySummary(
            id=municipality.id,
            istat_code=municipality.istat_code,
            name=municipality.canonical_name,
            region_id=region.id,
            region_name=region.canonical_name,
            province_abbreviation=municipality.province_abbreviation,
            status=municipality.status.value,
            current_mayor=mayor,
        )

    @staticmethod
    def _source(entity: Region | Municipality) -> PublicTerritorialSource:
        return PublicTerritorialSource(
            name=entity.source.name,
            url=entity.source_url,
        )
