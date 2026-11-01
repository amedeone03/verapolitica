from typing import Any
from datetime import date, datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from backend.app.models import EditorialPostStatus, FeedScope
from backend.app.schemas.candidate_profile import ImmutableSchema


class FeedItemKind(StrEnum):
    PROPOSAL_STATUS = "proposal_status"
    PLEDGE_VERDICT = "pledge_verdict"
    REFERENDUM = "referendum"
    EDITORIAL = "editorial"


class FeedFilter(StrEnum):
    ALL = "all"
    NATIONAL = "national"
    REGION = "region"
    PROVINCE = "province"
    MUNICIPALITY = "municipality"


class FeedSource(ImmutableSchema):
    title: str
    url: str


class FeedItem(ImmutableSchema):
    """One verified fact; ``key`` is stable so clients can de-duplicate."""

    key: str
    kind: FeedItemKind
    occurred_on: date
    title: str
    detail: str
    url: str
    scope: FeedScope
    region_id: int | None = None
    region_name: str | None = None
    province_abbreviation: str | None = None
    municipality_id: int | None = None
    municipality_name: str | None = None
    sources: tuple[FeedSource, ...] = ()
    label: str | None = None
    # Card details for the feed layout: type, actors, institution, summary, stage.
    card: dict[str, Any] | None = None
    # Present for news written with the nine-block model in the redazione console.
    blocks: dict[str, Any] | None = None
    written_by: str | None = None
    verified_by: str | None = None


class FeedPage(ImmutableSchema):
    filter: FeedFilter
    region_id: int | None
    province_abbreviation: str | None
    municipality_id: int | None
    items: tuple[FeedItem, ...]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=50)
    has_more: bool


class Citation(ImmutableSchema):
    title: str = Field(min_length=1, max_length=300)
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("citations must use https")
        return value


class EditorialPostRequest(ImmutableSchema):
    title: str = Field(min_length=5, max_length=300)
    body: str = Field(min_length=20, max_length=12000)
    scope: FeedScope
    region_id: int | None = Field(default=None, gt=0)
    province_abbreviation: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    municipality_id: int | None = Field(default=None, gt=0)
    citations: tuple[Citation, ...] = Field(min_length=1, max_length=10)
    corrects_id: int | None = Field(default=None, gt=0)
    author: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def _scope_target(self) -> "EditorialPostRequest":
        targets = {
            FeedScope.REGION: self.region_id,
            FeedScope.PROVINCE: self.province_abbreviation,
            FeedScope.MUNICIPALITY: self.municipality_id,
        }
        if self.scope in targets and targets[self.scope] is None:
            raise ValueError(f"scope {self.scope.value} needs its territory")
        return self


class EditorialReviewRequest(ImmutableSchema):
    reviewer: str | None = Field(default=None, min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=2000)


class EditorialPostResponse(ImmutableSchema):
    id: int
    title: str
    body: str
    scope: FeedScope
    region_id: int | None
    province_abbreviation: str | None
    municipality_id: int | None
    citations: tuple[FeedSource, ...]
    corrects_id: int | None
    status: EditorialPostStatus
    created_by: str
    reviewed_by: str | None
    review_note: str | None
    published_at: datetime | None
    created_at: datetime


class EditorialPostList(ImmutableSchema):
    items: tuple[EditorialPostResponse, ...]
    total: int = Field(ge=0)
