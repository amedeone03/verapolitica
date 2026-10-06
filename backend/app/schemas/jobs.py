from datetime import datetime
from typing import Any

from pydantic import Field

from backend.app.models import IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.candidate_profile import ImmutableSchema


class IngestionJobMetrics(ImmutableSchema):
    records_processed: int = Field(ge=0, default=0)
    records_created: int = Field(ge=0, default=0)
    records_updated: int = Field(ge=0, default=0)
    records_skipped: int = Field(ge=0, default=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionJobRunResult(ImmutableSchema):
    id: int = Field(gt=0)
    job_name: str
    source_key: str
    status: IngestionJobStatus
    trigger_type: IngestionJobTrigger
    started_at: datetime
    completed_at: datetime | None = None
    records_processed: int = Field(ge=0)
    records_created: int = Field(ge=0)
    records_updated: int = Field(ge=0)
    records_skipped: int = Field(ge=0)
    attempt_count: int = Field(ge=1)
    error_message: str | None = None
    duration_ms: int | None = None
    stale_recovered: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestionJobRunList(ImmutableSchema):
    items: tuple[IngestionJobRunResult, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
