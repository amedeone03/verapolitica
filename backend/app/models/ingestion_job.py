from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionJobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class IngestionJobTrigger(StrEnum):
    CLI = "cli"
    SCHEDULED = "scheduled"
    ADMIN = "admin"


class IngestionJobRun(Base):
    """Auditable execution of one official ingestion job."""

    __tablename__ = "ingestion_job_runs"
    __table_args__ = (
        Index("ix_ingestion_job_runs_name_started", "job_name", "started_at"),
        Index("ix_ingestion_job_runs_status_started", "status", "started_at"),
        Index(
            "uq_ingestion_job_runs_running_name",
            "job_name",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(80), index=True)
    source_key: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[IngestionJobStatus] = mapped_column(
        Enum(
            IngestionJobStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=16,
        ),
        default=IngestionJobStatus.RUNNING,
        index=True,
    )
    trigger_type: Mapped[IngestionJobTrigger] = mapped_column(
        Enum(
            IngestionJobTrigger,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            length=16,
        ),
        default=IngestionJobTrigger.CLI,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
