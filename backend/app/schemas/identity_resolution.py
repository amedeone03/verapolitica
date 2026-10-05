from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.app.models import IdentityResolutionStatus
from backend.app.schemas.candidate_profile import ImmutableSchema


class IdentityResolutionAttachment(ImmutableSchema):
    source_authority: str
    source_identifier: str
    status: Literal["attached", "already_exists"]


class IdentityResolutionCaseResult(ImmutableSchema):
    outcome: Literal["case_created", "case_reused"]
    case_id: int = Field(gt=0)
    status: IdentityResolutionStatus
    created: bool


class IdentityResolutionDecisionResult(ImmutableSchema):
    case_id: int = Field(gt=0)
    status: IdentityResolutionStatus
    resolved_politician_id: int | None
    reviewer_identity: str
    resolution_note: str | None
    resolved_at: datetime
    attachments: tuple[IdentityResolutionAttachment, ...] = ()
