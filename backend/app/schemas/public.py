from datetime import date, datetime

from pydantic import AnyHttpUrl, Field

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.politician import PoliticianVersionProfile


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


class PublicPolitician(PublicPoliticianSummary):
    citations: tuple[PublicCitation, ...]


class PublicPoliticianList(ImmutableSchema):
    items: tuple[PublicPoliticianSummary, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
