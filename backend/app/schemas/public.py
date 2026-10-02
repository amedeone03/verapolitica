from datetime import date, datetime

from pydantic import Field

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.politician import PoliticianVersionProfile


class PublicPolitician(ImmutableSchema):
    id: int = Field(gt=0)
    given_name: str
    family_name: str
    birth_date: date | None
    current_version_number: int = Field(gt=0)
    profile_schema_version: int = Field(gt=0)
    published_at: datetime
    profile: PoliticianVersionProfile


class PublicPoliticianList(ImmutableSchema):
    items: tuple[PublicPolitician, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
