from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models import (
    EvidenceExtractionMethod,
    IdentityResolutionStatus,
    ProfileDraftKind,
    ProfileDraftStatus,
    ReviewDecision,
)
from backend.app.schemas.candidate_profile import CandidateProfile
from backend.app.schemas.diff import ProfileDiff
from backend.app.schemas.politician import MatchingResult, PoliticianVersionProfile


class AdminAPISchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminPrincipal(AdminAPISchema):
    reviewer_identity: str


class APIErrorDetail(AdminAPISchema):
    code: str
    message: str
    details: Any = None


class APIErrorResponse(AdminAPISchema):
    error: APIErrorDetail


class ReviewNoteRequest(AdminAPISchema):
    note: str | None = Field(default=None, max_length=5000)


class PoliticianSummary(AdminAPISchema):
    id: int
    given_name: str
    family_name: str
    birth_date: date | None
    current_version_id: int | None


class DraftListItem(AdminAPISchema):
    id: int
    politician_id: int
    politician_name: str
    kind: ProfileDraftKind
    status: ProfileDraftStatus
    baseline_version_id: int | None
    created_at: datetime
    updated_at: datetime
    evidence_count: int
    change_count: int
    supersedes_id: int | None
    final_review_decision: ReviewDecision | None


class DraftListResponse(AdminAPISchema):
    items: tuple[DraftListItem, ...]
    total: int
    offset: int
    limit: int


class EvidenceResponse(AdminAPISchema):
    id: int
    field_path: str
    raw_document_id: int
    source_url: str
    source_record_identifier: str
    source_field_name: str
    source_value: str
    extraction_method: EvidenceExtractionMethod
    created_at: datetime


class RawDocumentSourceResponse(AdminAPISchema):
    id: int
    source_key: str
    source_name: str
    source_url: str
    retrieved_at: datetime
    raw_sha256: str
    normalized_sha256: str | None
    collector_version: str
    parser_version: str


class PoliticianVersionContext(AdminAPISchema):
    id: int
    version_number: int
    profile_schema_version: int
    profile_data: PoliticianVersionProfile
    created_at: datetime
    published_at: datetime | None


class FinalReviewResponse(AdminAPISchema):
    id: int
    reviewer: str
    decision: ReviewDecision
    note: str | None
    created_at: datetime


class DraftDetailResponse(AdminAPISchema):
    id: int
    politician: PoliticianSummary
    kind: ProfileDraftKind
    status: ProfileDraftStatus
    profile_schema_version: int
    baseline_version_id: int | None
    raw_document_id: int
    supersedes_id: int | None
    superseded_draft_ids: tuple[int, ...]
    superseded_by_draft_ids: tuple[int, ...]
    created_at: datetime
    updated_at: datetime
    proposed_profile: PoliticianVersionProfile
    diff: ProfileDiff
    evidence: tuple[EvidenceResponse, ...]
    source_document: RawDocumentSourceResponse
    baseline_version: PoliticianVersionContext | None
    current_version: PoliticianVersionContext | None
    final_review: FinalReviewResponse | None


class IdentityResolutionNoteRequest(AdminAPISchema):
    note: str | None = Field(default=None, max_length=5000)


class ResolveExistingIdentityRequest(IdentityResolutionNoteRequest):
    politician_id: int = Field(gt=0)


class IdentityResolutionSourceResponse(AdminAPISchema):
    id: int
    key: str
    name: str


class IdentitySourceIdentifierResponse(AdminAPISchema):
    authority: str
    value: str


class PossiblePoliticianMatchResponse(AdminAPISchema):
    politician: PoliticianSummary
    signals: tuple[str, ...]
    source_identifiers: tuple[IdentitySourceIdentifierResponse, ...]


class IdentityResolutionListItem(AdminAPISchema):
    id: int
    status: IdentityResolutionStatus
    candidate_display_name: str
    source: IdentityResolutionSourceResponse
    source_identifier: str
    official_source_url: str
    current_role: str | None
    birth_date: date | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolved_politician_id: int | None


class IdentityResolutionListResponse(AdminAPISchema):
    items: tuple[IdentityResolutionListItem, ...]
    total: int
    offset: int
    limit: int


class IdentityResolutionDetailResponse(AdminAPISchema):
    id: int
    status: IdentityResolutionStatus
    candidate_display_name: str
    candidate_snapshot: CandidateProfile
    matching_result: MatchingResult
    source: IdentityResolutionSourceResponse
    raw_document_id: int
    source_identifier: str
    official_source_url: str
    possible_matches: tuple[PossiblePoliticianMatchResponse, ...]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolved_politician_id: int | None
    reviewer_identity: str | None
    resolution_note: str | None
