from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from backend.app.models import ProfileDraftStatus, ReviewDecision
from backend.app.schemas.candidate_profile import ImmutableSchema


class ReviewStartedResult(ImmutableSchema):
    status: Literal["in_review"] = "in_review"
    draft_id: int = Field(gt=0)
    politician_id: int = Field(gt=0)
    final_draft_status: Literal[ProfileDraftStatus.IN_REVIEW] = (
        ProfileDraftStatus.IN_REVIEW
    )


class ReviewDecisionResult(ImmutableSchema):
    status: Literal["reviewed"] = "reviewed"
    review_id: int = Field(gt=0)
    decision: ReviewDecision
    draft_id: int = Field(gt=0)
    politician_id: int = Field(gt=0)
    created_version_id: int | None = Field(default=None, gt=0)
    version_number: int | None = Field(default=None, gt=0)
    current_version_id: int | None = Field(default=None, gt=0)
    final_draft_status: ProfileDraftStatus


ReviewResult: TypeAlias = Annotated[
    ReviewStartedResult | ReviewDecisionResult,
    Field(discriminator="status"),
]
