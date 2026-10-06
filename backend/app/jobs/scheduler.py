from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.jobs.catalog import enabled_schedules
from backend.app.jobs.service import IngestionJobConflictError, IngestionJobService
from backend.app.models import IngestionJobTrigger


logger = logging.getLogger("verapolitica.jobs")


class IngestionScheduler:
    """Register cron-configured ingestion jobs without owning domain logic."""

    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.scheduler = scheduler or BackgroundScheduler(timezone="UTC")

    def register(self) -> tuple[str, ...]:
        registered: list[str] = []
        for spec, cron in enabled_schedules(self.settings):
            try:
                trigger = CronTrigger.from_crontab(cron, timezone="UTC")
            except (ValueError, TypeError) as exc:
                logger.error(
                    "invalid cron %r for job %s: %s",
                    cron,
                    spec.job_name,
                    exc,
                )
                continue
            self.scheduler.add_job(
                self._execute,
                trigger=trigger,
                id=spec.job_name,
                args=[spec.job_name],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            registered.append(spec.job_name)
            logger.info("registered scheduled job %s cron=%s", spec.job_name, cron)
        return tuple(registered)

    def registered_job_names(self) -> tuple[str, ...]:
        return tuple(job.id for job in self.scheduler.get_jobs())

    def start(self) -> tuple[str, ...]:
        recovered = IngestionJobService(
            self.session_factory, self.settings
        ).recover_stale_runs()
        if recovered:
            logger.warning("scheduler recovered %s stale running job(s)", recovered)
        names = self.register()
        if names:
            self.scheduler.start()
        return names

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _execute(self, job_name: str) -> None:
        try:
            result = IngestionJobService(self.session_factory, self.settings).execute(
                job_name,
                trigger_type=IngestionJobTrigger.SCHEDULED,
            )
            logger.info(
                "scheduled job %s run %s status=%s",
                job_name,
                result.id,
                result.status.value,
            )
        except IngestionJobConflictError:
            logger.warning("skip overlapping scheduled job %s", job_name)
        except Exception:
            logger.exception("scheduled job %s failed unexpectedly", job_name)
