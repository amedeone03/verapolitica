from datetime import date

from pydantic import Field

from backend.app.models import Chamber, HistoricalEra
from backend.app.schemas.candidate_profile import ImmutableSchema


class PublicLegislature(ImmutableSchema):
    number: int = Field(ge=0)
    label: str
    roman: str
    era: HistoricalEra
    era_label: str
    start_date: date
    end_date: date | None
    source_url: str
    camera_mandates: int = Field(ge=0)
    senato_mandates: int = Field(ge=0)


class PublicEra(ImmutableSchema):
    era: HistoricalEra
    label: str
    note: str
    legislatures: tuple[PublicLegislature, ...]


class PublicEraList(ImmutableSchema):
    eras: tuple[PublicEra, ...]


class PublicHistoricalMandate(ImmutableSchema):
    id: int
    chamber: Chamber
    legislature: int
    given_name: str
    family_name: str
    start_date: date | None
    end_date: date | None
    election_area: str | None
    group_name: str | None
    source_url: str
    politician_id: int | None = None


class PublicHistoricalMandateList(ImmutableSchema):
    items: tuple[PublicHistoricalMandate, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)


class PublicArchiveReferendum(ImmutableSchema):
    id: int
    title: str
    vote_date: date
    scope_type: str


class PublicLegislatureDetail(ImmutableSchema):
    legislature: PublicLegislature
    previous: int | None
    next: int | None
    referendums: tuple[PublicArchiveReferendum, ...]
    published_proposals: int = Field(ge=0)


class PublicProvince(ImmutableSchema):
    abbreviation: str
    name: str
    region_id: int
    region_name: str
    municipalities: int = Field(ge=0)
    logo_url: str | None = None


class PublicProvinceList(ImmutableSchema):
    items: tuple[PublicProvince, ...]
    total: int = Field(ge=0)


class PublicOfficeHolder(ImmutableSchema):
    politician_id: int
    name: str
    office: str
    territory_id: int
    territory_name: str
    start_date: date | None
    end_date: date | None
    source_url: str


class PublicTerritoryHistory(ImmutableSchema):
    """What VeraPolitica has published about a region or province, oldest first."""

    kind: str
    name: str
    region_id: int
    province_abbreviation: str | None = None
    office_holders: tuple[PublicOfficeHolder, ...]
    referendums: tuple[PublicArchiveReferendum, ...]
    coverage_note: str
