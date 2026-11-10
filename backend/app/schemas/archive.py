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


class PublicLegislatureLaw(ImmutableSchema):
    """A published bill of this legislature, for the 'questa legge in questa legislatura' view."""

    id: int
    title: str
    status: str
    introduced_at: date | None = None


class PublicLegislatureDetail(ImmutableSchema):
    legislature: PublicLegislature
    previous: int | None
    next: int | None
    referendums: tuple[PublicArchiveReferendum, ...]
    published_proposals: int = Field(ge=0)
    enacted_laws: tuple[PublicLegislatureLaw, ...] = ()


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


class PublicArchiveTimelineSummary(ImmutableSchema):
    """Index row for a city, region or national draft timeline."""

    kind: str
    name: str
    slug: str
    event_count: int
    verified_count: int = 0
    draft: bool = True
    municipality_id: int | None = None
    province_abbreviation: str | None = None
    region_id: int | None = None


class PublicArchiveTimelineList(ImmutableSchema):
    items: tuple[PublicArchiveTimelineSummary, ...]
    disclaimer: str


class PublicArchiveTimelineEvent(ImmutableSchema):
    date: str
    date_label: str
    title: str
    body: str
    status: str = ""
    sources: tuple[str, ...] = ()
    verified: bool = False
    official_url: str | None = None
    official_name: str | None = None


class PublicArchiveTimeline(ImmutableSchema):
    """Editorial draft of election chronology. Not an official fact until verified."""

    kind: str
    name: str
    slug: str
    draft: bool = True
    updated: str | None = None
    mayor: str | None = None
    disclaimer: str
    verified_count: int = 0
    events: tuple[PublicArchiveTimelineEvent, ...]
    municipality_id: int | None = None
    province_abbreviation: str | None = None
    region_id: int | None = None
