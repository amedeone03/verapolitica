from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AIExtractionEvaluationRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class AIExtractionEvaluationRun(Base):
    __tablename__ = "ai_extraction_evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    evaluator_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[AIExtractionEvaluationRunStatus] = mapped_column(
        Enum(
            AIExtractionEvaluationRunStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=32,
        ),
        index=True,
    )
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_case_count: Mapped[int] = mapped_column(Integer, default=0)
    aggregate_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    case_results: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    thresholds_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error_summary: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
