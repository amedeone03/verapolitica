from enum import StrEnum
from typing import Any

from pydantic import Field

from backend.app.schemas.candidate_profile import ImmutableSchema


class SearchEntityType(StrEnum):
    POLITICIAN = "politician"
    PROPOSAL = "proposal"
    REFERENDUM = "referendum"
    MUNICIPALITY = "municipality"
    REGION = "region"
    PARLIAMENTARY_GROUP = "parliamentary_group"
    POLITICAL_PARTY = "political_party"
    GLOSSARY_TERM = "glossary_term"


class PublicSearchResult(ImmutableSchema):
    entity_type: SearchEntityType
    title: str
    subtitle: str
    url: str
    snippet: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublicSearchResultList(ImmutableSchema):
    query: str
    normalized_query: str
    entity_type: SearchEntityType | None = None
    items: tuple[PublicSearchResult, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=50)


class PublicParliamentaryGroup(ImmutableSchema):
    id: int = Field(gt=0)
    name: str
    abbreviation: str | None = None
    institution: str
    legislature: str


class PublicPoliticalParty(ImmutableSchema):
    id: int = Field(gt=0)
    name: str
    abbreviation: str | None = None
