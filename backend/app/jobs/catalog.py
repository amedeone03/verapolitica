from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings
from backend.app.jobs.runners import (
    run_civic_reminders,
    run_politician_ingestion,
    run_proposal_ingestion,
    run_territorial_office_ingestion,
    run_territory_ingestion,
)
from backend.app.schemas.jobs import IngestionJobMetrics


Runner = Callable[[Settings, sessionmaker[Session]], IngestionJobMetrics]


@dataclass(frozen=True, slots=True)
class JobSpec:
    job_name: str
    source_key: str
    runner: Runner
    schedule_attr: str


JOB_CATALOG: dict[str, JobSpec] = {
    "senato": JobSpec(
        "senato",
        "senato-repubblica",
        lambda settings, factory: run_politician_ingestion(
            settings, factory, "senato"
        ),
        "schedule_senato_cron",
    ),
    "camera": JobSpec(
        "camera",
        "camera-deputati",
        lambda settings, factory: run_politician_ingestion(
            settings, factory, "camera"
        ),
        "schedule_camera_cron",
    ),
    "governo": JobSpec(
        "governo",
        "governo-italiano",
        lambda settings, factory: run_politician_ingestion(
            settings, factory, "governo"
        ),
        "schedule_governo_cron",
    ),
    "proposals": JobSpec(
        "proposals",
        "senato-ddl",
        run_proposal_ingestion,
        "schedule_proposals_cron",
    ),
    "territories": JobSpec(
        "territories",
        "istat-territories",
        run_territory_ingestion,
        "schedule_territories_cron",
    ),
    "territorial-offices": JobSpec(
        "territorial-offices",
        "dait-current-mayors",
        run_territorial_office_ingestion,
        "schedule_territorial_offices_cron",
    ),
    "civic-reminders": JobSpec(
        "civic-reminders",
        "civic-reminders",
        run_civic_reminders,
        "schedule_civic_reminders_cron",
    ),
}


def enabled_schedules(settings: Settings) -> tuple[tuple[JobSpec, str], ...]:
    enabled: list[tuple[JobSpec, str]] = []
    for spec in JOB_CATALOG.values():
        expression = getattr(settings, spec.schedule_attr, "") or ""
        cron = expression.strip()
        if cron:
            enabled.append((spec, cron))
    return tuple(enabled)
