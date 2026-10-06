from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.jobs.catalog import JOB_CATALOG, JobSpec
from backend.app.jobs.runners import TransientIngestionError
from backend.app.models import (
    IngestionJobRun,
    IngestionJobStatus,
    IngestionJobTrigger,
)
from backend.app.schemas.jobs import (
    IngestionJobMetrics,
    IngestionJobRunList,
    IngestionJobRunResult,
)


logger = logging.getLogger("verapolitica.jobs")


class IngestionJobError(RuntimeError):
    pass


class IngestionJobValidationError(IngestionJobError):
    pass


class IngestionJobConflictError(IngestionJobError):
    pass


class IngestionJobNotFoundError(IngestionJobError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestionJobService:
    """Persist job-run state around existing ingestion pipelines."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        runners: Mapping[str, Callable[[Settings, sessionmaker[Session]], IngestionJobMetrics]]
        | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.runners = dict(runners or {name: spec.runner for name, spec in JOB_CATALOG.items()})

    def execute(
        self,
        job_name: str,
        *,
        trigger_type: IngestionJobTrigger = IngestionJobTrigger.CLI,
    ) -> IngestionJobRunResult:
        spec = self._spec(job_name)
        recovered = self.recover_stale_runs()
        if recovered:
            logger.warning(
                "recovered %s stale running job(s) before starting %s",
                recovered,
                spec.job_name,
            )
        run = self._start(spec, trigger_type)
        started = time.monotonic()
        logger.info(
            "job %s run %s source=%s status=running trigger=%s",
            spec.job_name,
            run.id,
            spec.source_key,
            trigger_type.value,
        )
        attempts = 0
        last_error: Exception | None = None
        max_retries = self.settings.job_max_retries
        while attempts <= max_retries:
            attempts += 1
            try:
                metrics = self.runners[spec.job_name](self.settings, self.session_factory)
                result = self._finish(
                    run.id,
                    IngestionJobStatus.SUCCEEDED,
                    metrics=metrics,
                    attempt_count=attempts,
                )
                logger.info(
                    "job %s run %s source=%s status=%s duration_ms=%s processed=%s created=%s updated=%s skipped=%s",
                    spec.job_name,
                    result.id,
                    spec.source_key,
                    result.status.value,
                    int((time.monotonic() - started) * 1000),
                    result.records_processed,
                    result.records_created,
                    result.records_updated,
                    result.records_skipped,
                )
                return result
            except TransientIngestionError as exc:
                last_error = exc
                if attempts <= max_retries:
                    time.sleep(self.settings.job_retry_backoff_seconds * attempts)
                    continue
            except Exception as exc:
                last_error = exc
                break
        message = str(last_error or "ingestion job failed")[:4000]
        result = self._finish(
            run.id,
            IngestionJobStatus.FAILED,
            attempt_count=attempts,
            error_message=message,
        )
        logger.error(
            "job %s run %s source=%s status=%s duration_ms=%s error=%s",
            spec.job_name,
            result.id,
            spec.source_key,
            result.status.value,
            int((time.monotonic() - started) * 1000),
            message,
        )
        return result

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        job_name: str | None = None,
        status: IngestionJobStatus | None = None,
    ) -> IngestionJobRunList:
        with self.session_factory() as session:
            query = select(IngestionJobRun)
            count_query = select(func.count()).select_from(IngestionJobRun)
            if job_name is not None:
                query = query.where(IngestionJobRun.job_name == job_name)
                count_query = count_query.where(IngestionJobRun.job_name == job_name)
            if status is not None:
                query = query.where(IngestionJobRun.status == status)
                count_query = count_query.where(IngestionJobRun.status == status)
            total = session.scalar(count_query) or 0
            rows = list(
                session.scalars(
                    query.order_by(IngestionJobRun.started_at.desc(), IngestionJobRun.id.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            return IngestionJobRunList(
                items=tuple(self._result(row) for row in rows),
                total=total,
                offset=offset,
                limit=limit,
            )

    def get(self, job_run_id: int) -> IngestionJobRunResult:
        with self.session_factory() as session:
            run = session.get(IngestionJobRun, job_run_id)
            if run is None:
                raise IngestionJobNotFoundError(f"job run {job_run_id} does not exist")
            return self._result(run)

    def recover_stale_runs(self) -> int:
        """Mark running jobs older than the configured threshold as failed.

        History rows are retained. A fresh running job still blocks overlap.
        """

        cutoff = _now() - timedelta(minutes=self.settings.job_stale_after_minutes)
        recovered = 0
        with self.session_factory() as session:
            with session.begin():
                rows = list(
                    session.scalars(
                        select(IngestionJobRun).where(
                            IngestionJobRun.status == IngestionJobStatus.RUNNING
                        )
                    )
                )
                for run in rows:
                    started = run.started_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    if started > cutoff:
                        continue
                    metadata = dict(run.job_metadata or {})
                    metadata["stale_recovered"] = True
                    metadata["stale_after_minutes"] = (
                        self.settings.job_stale_after_minutes
                    )
                    run.status = IngestionJobStatus.FAILED
                    run.completed_at = _now()
                    run.error_message = (
                        "stale running job recovered after "
                        f"{self.settings.job_stale_after_minutes} minutes"
                    )
                    run.job_metadata = metadata
                    recovered += 1
                    logger.warning(
                        "job %s run %s marked stale",
                        run.job_name,
                        run.id,
                    )
        return recovered

    def _spec(self, job_name: str) -> JobSpec:
        spec = JOB_CATALOG.get(job_name)
        if spec is None or job_name not in self.runners:
            raise IngestionJobValidationError(f"unknown ingestion job {job_name!r}")
        return spec

    def _start(
        self, spec: JobSpec, trigger_type: IngestionJobTrigger
    ) -> IngestionJobRunResult:
        try:
            with self.session_factory() as session:
                with session.begin():
                    run = IngestionJobRun(
                        job_name=spec.job_name,
                        source_key=spec.source_key,
                        status=IngestionJobStatus.RUNNING,
                        trigger_type=trigger_type,
                        started_at=_now(),
                        job_metadata={},
                    )
                    session.add(run)
                    session.flush()
                    return self._result(run)
        except IntegrityError as exc:
            raise IngestionJobConflictError(
                f"ingestion job {spec.job_name!r} is already running"
            ) from exc

    def _finish(
        self,
        run_id: int,
        status: IngestionJobStatus,
        *,
        metrics: IngestionJobMetrics | None = None,
        attempt_count: int,
        error_message: str | None = None,
    ) -> IngestionJobRunResult:
        with self.session_factory() as session:
            with session.begin():
                run = session.get(IngestionJobRun, run_id)
                if run is None:
                    raise IngestionJobNotFoundError(f"job run {run_id} does not exist")
                run.status = status
                run.completed_at = _now()
                run.attempt_count = attempt_count
                run.error_message = error_message
                if metrics is not None:
                    run.records_processed = metrics.records_processed
                    run.records_created = metrics.records_created
                    run.records_updated = metrics.records_updated
                    run.records_skipped = metrics.records_skipped
                    run.job_metadata = metrics.metadata
                return self._result(run)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _result(cls, run: IngestionJobRun) -> IngestionJobRunResult:
        duration_ms = None
        if run.completed_at is not None and run.started_at is not None:
            duration_ms = int(
                (cls._aware(run.completed_at) - cls._aware(run.started_at)).total_seconds()
                * 1000
            )
        metadata = run.job_metadata or {}
        return IngestionJobRunResult(
            id=run.id,
            job_name=run.job_name,
            source_key=run.source_key,
            status=run.status,
            trigger_type=run.trigger_type,
            started_at=run.started_at,
            completed_at=run.completed_at,
            records_processed=run.records_processed,
            records_created=run.records_created,
            records_updated=run.records_updated,
            records_skipped=run.records_skipped,
            attempt_count=run.attempt_count,
            error_message=run.error_message,
            duration_ms=max(duration_ms, 0) if duration_ms is not None else None,
            stale_recovered=bool(metadata.get("stale_recovered")),
            metadata=metadata,
        )
