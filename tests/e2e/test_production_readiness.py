from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import AppEnvironment, Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.jobs.service import IngestionJobConflictError, IngestionJobService
from backend.app.main import create_app
from backend.app.models import IngestionJobRun, IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.jobs import IngestionJobMetrics


def test_production_like_isolated_surface(tmp_path):
    database = tmp_path / "prod-like.db"
    settings = Settings(
        env=AppEnvironment.TEST,
        database_url=f"sqlite:///{database}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        trusted_hosts="testserver",
        cors_origins="https://verapolitica.it",
        enable_demo_ui=False,
        enable_api_docs=False,
        log_format="json",
        job_stale_after_minutes=30,
        job_max_retries=0,
    )
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    try:
        stale_start = datetime.now(timezone.utc) - timedelta(minutes=90)
        with factory() as session:
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

        app = create_app(settings)
        with TestClient(app) as client:
            assert client.get("/health/live").status_code == 200
            ready = client.get("/health/ready")
            assert ready.status_code == 200
            assert client.get("/search", params={"q": "test", "limit": 1}).status_code == 200
            assert client.get("/politicians").status_code == 200
            assert client.get("/proposals").status_code == 200
            assert client.get("/referendums").status_code == 200
            assert client.get("/glossary").status_code == 200
            assert client.get("/regions").status_code == 200
            assert client.get("/admin/jobs").status_code == 401
            assert client.get("/demo/").status_code == 404
            assert client.get("/docs").status_code == 404
            assert "database_url" not in ready.text.casefold()

        service = IngestionJobService(
            factory,
            settings,
            runners={
                "senato": lambda runtime, session_factory: IngestionJobMetrics(
                    records_processed=1
                )
            },
        )
        assert service.recover_stale_runs() == 1
        result = service.execute("senato")
        assert result.status is IngestionJobStatus.SUCCEEDED

        with factory() as session:
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
        blocked = IngestionJobService(
            factory,
            settings,
            runners={"camera": lambda runtime, session_factory: IngestionJobMetrics()},
        )
        with pytest.raises(IngestionJobConflictError):
            blocked.execute("camera")
    finally:
        engine.dispose()
