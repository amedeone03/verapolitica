from datetime import date

from pydantic import Field

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.politician import MatchingMethod


class BootstrapSourceIdentifier(ImmutableSchema):
    authority: str
    value: str


class BootstrapNewDetail(ImmutableSchema):
    candidate_index: int = Field(ge=0)
    display_name: str
    birth_date: date | None = None
    source_identifiers: tuple[BootstrapSourceIdentifier, ...]
    created_politician_id: int | None = Field(default=None, gt=0)


class BootstrapMatchedDetail(ImmutableSchema):
    candidate_index: int = Field(ge=0)
    display_name: str
    politician_id: int = Field(gt=0)
    method: MatchingMethod


class BootstrapUncertainDetail(ImmutableSchema):
    candidate_index: int = Field(ge=0)
    display_name: str
    candidate_politician_ids: tuple[int, ...]
    method: MatchingMethod


class BootstrapInvalidDetail(ImmutableSchema):
    candidate_index: int = Field(ge=0)
    source_record_id: str | None = None
    display_name: str | None = None
    error: str


class BootstrapReport(ImmutableSchema):
    raw_document_id: int | None = Field(default=None, gt=0)
    dry_run: bool
    applied: bool
    safe_to_apply: bool
    total_candidates: int = Field(ge=0)
    new_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    uncertain_count: int = Field(ge=0)
    invalid_count: int = Field(ge=0)
    politicians_would_create: int = Field(ge=0)
    identifiers_would_create: int = Field(ge=0)
    politicians_created: int = Field(ge=0)
    identifiers_created: int = Field(ge=0)
    new: tuple[BootstrapNewDetail, ...]
    matched: tuple[BootstrapMatchedDetail, ...]
    uncertain: tuple[BootstrapUncertainDetail, ...]
    invalid: tuple[BootstrapInvalidDetail, ...]
