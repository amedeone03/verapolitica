from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from backend.app.schemas.candidate_profile import ImmutableSchema
from backend.app.schemas.diff import DiffStatus, ProfileDiff


class DraftCreatedResult(ImmutableSchema):
    status: Literal["draft_created"] = "draft_created"
    draft_id: int = Field(gt=0)
    politician_id: int = Field(gt=0)
    baseline_version_id: int | None = Field(default=None, gt=0)
    kind: DiffStatus
    evidence_count: int = Field(ge=0)
    superseded_draft_ids: tuple[int, ...]
    diff: ProfileDiff


class NoChangesResult(ImmutableSchema):
    status: Literal["no_changes"] = "no_changes"
    politician_id: int = Field(gt=0)
    baseline_version_id: int = Field(gt=0)


DraftResult: TypeAlias = Annotated[
    DraftCreatedResult | NoChangesResult,
    Field(discriminator="status"),
]
