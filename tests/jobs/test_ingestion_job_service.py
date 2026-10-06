from datetime import datetime, timezone

import pytest

from backend.app.core.config import Settings
from backend.app.jobs.runners import TransientIngestionError
from backend.app.jobs.service import (
    IngestionJobConflictError,
    IngestionJobService,
)
from backend.app.models import IngestionJobRun, IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.jobs import IngestionJobMetrics


def _settings() -> Settings:
    return Settings(job_max_retries=1, job_retry_backoff_seconds=0.01)


def test_job_run_creation_and_success(session_factory):
    def runner(settings, factory):
        del settings, factory
        return IngestionJobMetrics(
            records_processed=5,
            records_created=2,
            records_updated=1,
            records_skipped=2,
            metadata={"source": "fixture"},
        )

    service = IngestionJobService(
        session_factory, _settings(), runners={"senato": runner}
    )
    result = service.execute("senato")
    assert result.status is IngestionJobStatus.SUCCEEDED
    assert result.records_processed == 5
    assert result.records_created == 2
    assert result.records_updated == 1
    assert result.records_skipped == 2
    assert result.attempt_count == 1
    assert result.error_message is None
    assert result.metadata == {"source": "fixture"}
    history = service.list(job_name="senato")
    assert history.total == 1
    assert history.items[0].id == result.id
    loaded = service.get(result.id)
    assert loaded.status is IngestionJobStatus.SUCCEEDED


def test_failed_job_persists_error(session_factory):
    def runner(settings, factory):
        del settings, factory
        raise ValueError("malformed official payload")

    service = IngestionJobService(
        session_factory, _settings(), runners={"camera": runner}
    )
    result = service.execute("camera")
    assert result.status is IngestionJobStatus.FAILED
    assert result.attempt_count == 1
    assert "malformed official payload" in (result.error_message or "")
    with session_factory() as session:
        stored = session.get(IngestionJobRun, result.id)
        assert stored is not None
        assert stored.status is IngestionJobStatus.FAILED
        assert stored.completed_at is not None


def test_overlapping_job_is_rejected(session_factory):
    with session_factory() as session:
        session.add(
            IngestionJobRun(
                job_name="governo",
                source_key="governo-italiano",
                status=IngestionJobStatus.RUNNING,
                trigger_type=IngestionJobTrigger.CLI,
                started_at=datetime.now(timezone.utc),
                job_metadata={},
            )
        )
        session.commit()

    service = IngestionJobService(
        session_factory,
        _settings(),
        runners={
            "governo": lambda settings, factory: IngestionJobMetrics()
        },
    )
    with pytest.raises(IngestionJobConflictError):
        service.execute("governo")


def test_retry_limit_for_transient_failures(session_factory):
    attempts = {"count": 0}

    def runner(settings, factory):
        del settings, factory
        attempts["count"] += 1
        raise TransientIngestionError("timeout contacting source")

    service = IngestionJobService(
        session_factory, _settings(), runners={"proposals": runner}
    )
    result = service.execute("proposals")
    assert result.status is IngestionJobStatus.FAILED
    assert attempts["count"] == 2
    assert result.attempt_count == 2
    assert "timeout" in (result.error_message or "")


def test_transient_retry_then_success(session_factory):
    attempts = {"count": 0}

    def runner(settings, factory):
        del settings, factory
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TransientIngestionError("connection reset")
        return IngestionJobMetrics(records_processed=1, records_created=1)

    service = IngestionJobService(
        session_factory, _settings(), runners={"territories": runner}
    )
    result = service.execute("territories")
    assert result.status is IngestionJobStatus.SUCCEEDED
    assert attempts["count"] == 2
    assert result.attempt_count == 2


def test_completed_job_releases_overlap_lock(session_factory):
    def runner(settings, factory):
        del settings, factory
        return IngestionJobMetrics(records_processed=1)

    service = IngestionJobService(
        session_factory, _settings(), runners={"senato": runner}
    )
    first = service.execute("senato")
    second = service.execute("senato")
    assert first.status is IngestionJobStatus.SUCCEEDED
    assert second.status is IngestionJobStatus.SUCCEEDED
    assert first.id != second.id
