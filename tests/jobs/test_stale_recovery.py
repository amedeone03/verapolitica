from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import ValidationError

from backend.app.core.config import AppEnvironment, ProductionConfigError, Settings
from backend.app.jobs.scheduler import IngestionScheduler
from backend.app.jobs.service import IngestionJobConflictError, IngestionJobService
from backend.app.models import IngestionJobRun, IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.jobs import IngestionJobMetrics


def test_production_requires_postgresql():
    with pytest.raises((ProductionConfigError, ValidationError), match="PostgreSQL"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="sqlite:///./data/verapolitica.db",
            admin_api_key="a-sufficiently-long-admin-token",
            cors_origins="https://verapolitica.it",
            trusted_hosts="verapolitica.it",
        )


def test_production_requires_strong_admin_key():
    with pytest.raises((ProductionConfigError, ValidationError), match="ADMIN_API_KEY"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
            admin_api_key="short",
            cors_origins="https://verapolitica.it",
            trusted_hosts="verapolitica.it",
        )


def test_production_rejects_wildcard_cors_and_hosts():
    with pytest.raises((ProductionConfigError, ValidationError), match="CORS"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
            admin_api_key="a-sufficiently-long-admin-token",
            cors_origins="*",
            trusted_hosts="verapolitica.it",
        )
    with pytest.raises((ProductionConfigError, ValidationError), match="TRUSTED_HOSTS"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
            admin_api_key="a-sufficiently-long-admin-token",
            cors_origins="https://verapolitica.it",
            trusted_hosts="*",
        )


def test_production_ai_requires_secret_when_provider_set():
    with pytest.raises((ProductionConfigError, ValidationError), match="LLM_API_KEY"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
            admin_api_key="a-sufficiently-long-admin-token",
            cors_origins="https://verapolitica.it",
            trusted_hosts="verapolitica.it",
            llm_provider="openai",
            llm_model="gpt-4.1-mini",
        )


def test_production_requires_admin_key():
    with pytest.raises((ProductionConfigError, ValidationError), match="ADMIN_API_KEY"):
        Settings(
            env=AppEnvironment.PRODUCTION,
            database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
            admin_api_key=None,
            cors_origins="https://verapolitica.it",
            trusted_hosts="verapolitica.it",
        )


def test_production_accepts_explicit_safe_settings():
    settings = Settings(
        env=AppEnvironment.PRODUCTION,
        database_url="postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
        admin_api_key="a-sufficiently-long-admin-token",
        cors_origins="https://verapolitica.it",
        trusted_hosts="verapolitica.it,www.verapolitica.it",
        raw_storage_path="./data/raw",
        log_format="json",
    )
    assert settings.is_production
    assert settings.demo_ui_enabled is False
    assert settings.api_docs_enabled is False
    assert settings.resolved_log_format == "json"
    assert settings.ai_extraction_enabled is False


def test_scheduler_start_recovers_stale_runs(session_factory):
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=90)
    with session_factory() as session:
        session.add(
            IngestionJobRun(
                job_name="governo",
                source_key="governo-italiano",
                status=IngestionJobStatus.RUNNING,
                trigger_type=IngestionJobTrigger.SCHEDULED,
                started_at=stale_start,
                job_metadata={},
            )
        )
        session.commit()
    scheduler = IngestionScheduler(
        Settings(job_stale_after_minutes=30),
        session_factory,
        scheduler=BackgroundScheduler(timezone="UTC"),
    )
    assert scheduler.start() == ()
    history = IngestionJobService(session_factory, Settings()).list(job_name="governo")
    assert history.items[0].stale_recovered is True
    assert history.items[0].status is IngestionJobStatus.FAILED
    scheduler.shutdown()


def test_stale_job_recovery_allows_new_run(session_factory):
    stale_start = datetime.now(timezone.utc) - timedelta(minutes=90)
    with session_factory() as session:
        session.add(
            IngestionJobRun(
                job_name="senato",
                source_key="senato-repubblica",
                status=IngestionJobStatus.RUNNING,
                trigger_type=IngestionJobTrigger.CLI,
                started_at=stale_start,
                job_metadata={},
            )
        )
        session.commit()
    service = IngestionJobService(
        session_factory,
        Settings(job_stale_after_minutes=30, job_max_retries=0),
        runners={"senato": lambda settings, factory: IngestionJobMetrics(records_processed=1)},
    )
    recovered = service.recover_stale_runs()
    assert recovered == 1
    result = service.execute("senato")
    assert result.status is IngestionJobStatus.SUCCEEDED
    history = service.list(job_name="senato")
    assert history.total == 2
    assert any(item.stale_recovered for item in history.items)


def test_fresh_running_job_still_blocks_overlap(session_factory):
    with session_factory() as session:
        session.add(
            IngestionJobRun(
                job_name="camera",
                source_key="camera-deputati",
                status=IngestionJobStatus.RUNNING,
                trigger_type=IngestionJobTrigger.CLI,
                started_at=datetime.now(timezone.utc),
                job_metadata={},
            )
        )
        session.commit()
    service = IngestionJobService(
        session_factory,
        Settings(job_stale_after_minutes=60, job_max_retries=0),
        runners={"camera": lambda settings, factory: IngestionJobMetrics()},
    )
    assert service.recover_stale_runs() == 0
    with pytest.raises(IngestionJobConflictError):
        service.execute("camera")
