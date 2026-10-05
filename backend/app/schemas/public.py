from datetime import date, datetime

from pydantic import AnyHttpUrl, Field

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.politician import PoliticianVersionProfile
from backend.app.schemas.proposal import PublicPoliticianProposal


class PublicCitation(ImmutableSchema):
    field_path: str
    source_name: str
    source_url: AnyHttpUrl
    source_field: str | None = None


class PublicPoliticianSummary(ImmutableSchema):
    id: int = Field(gt=0)
    given_name: str
    family_name: str
    birth_date: date | None
    current_version_number: int = Field(gt=0)
    profile_schema_version: int = Field(gt=0)
    published_at: datetime
    profile: PoliticianVersionProfile
    citation_count: int = Field(ge=0)


class PublicParliamentaryGroupSource(ImmutableSchema):
    name: str
    url: AnyHttpUrl


class PublicParliamentaryGroupMembership(ImmutableSchema):
    name: str
    abbreviation: str | None
    institution: str
    legislature: str
    start_date: date | None
    end_date: date | None
    role: str | None
    source: PublicParliamentaryGroupSource


class PublicPoliticalPartySource(ImmutableSchema):
    name: str
    url: AnyHttpUrl


class PublicPoliticalPartyAffiliation(ImmutableSchema):
    name: str
    abbreviation: str | None
    official_website_url: AnyHttpUrl | None
    start_date: date | None
    end_date: date | None
    affiliation_type: str | None
    source: PublicPoliticalPartySource


class PublicPolitician(PublicPoliticianSummary):
    citations: tuple[PublicCitation, ...]
    parliamentary_groups: tuple[PublicParliamentaryGroupMembership, ...] = ()
    political_parties: tuple[PublicPoliticalPartyAffiliation, ...] = ()
    proposals: tuple[PublicPoliticianProposal, ...] = ()
    territorial_offices: tuple["PublicTerritorialOffice", ...] = ()


class PublicPoliticianList(ImmutableSchema):
    items: tuple[PublicPoliticianSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class PublicTerritorialSource(ImmutableSchema):
    name: str
    url: AnyHttpUrl


class PublicOfficeHolder(ImmutableSchema):
    politician_id: int | None = Field(default=None, gt=0)
    given_name: str
    family_name: str
    start_date: date | None = None


class PublicRegionSummary(ImmutableSchema):
    id: int = Field(gt=0)
    istat_code: str
    name: str
    status: str
    current_president: PublicOfficeHolder | None = None


class PublicRegion(PublicRegionSummary):
    municipality_count: int = Field(ge=0)
    source: PublicTerritorialSource


class PublicRegionList(ImmutableSchema):
    items: tuple[PublicRegionSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class PublicMunicipalitySummary(ImmutableSchema):
    id: int = Field(gt=0)
    istat_code: str
    name: str
    region_id: int = Field(gt=0)
    region_name: str
    province_abbreviation: str
    status: str
    current_mayor: PublicOfficeHolder | None = None


class PublicMunicipality(PublicMunicipalitySummary):
    province_name: str
    source: PublicTerritorialSource


class PublicMunicipalityList(ImmutableSchema):
    items: tuple[PublicMunicipalitySummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)


class PublicTerritorialOffice(ImmutableSchema):
    office: str
    municipality: str | None = None
    municipality_id: int | None = Field(default=None, gt=0)
    region: str | None = None
    region_id: int | None = Field(default=None, gt=0)
    start_date: date
    end_date: date | None = None
    source: PublicTerritorialSource
