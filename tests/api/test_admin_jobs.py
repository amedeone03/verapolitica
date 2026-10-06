from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine, create_session_factory
from backend.app.jobs.catalog import JobSpec
from backend.app.main import create_app
from backend.app.models import IngestionJobRun, IngestionJobStatus, IngestionJobTrigger
from backend.app.schemas.jobs import IngestionJobMetrics


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'jobs-api.db'}",
        raw_storage_path=tmp_path / "raw",
        admin_api_key="test-admin-secret",
        admin_reviewer_identity="api-editor",
        job_max_retries=0,
        job_retry_backoff_seconds=0.01,
    )


def _seed_schema(settings: Settings) -> None:
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def test_admin_jobs_require_authentication(tmp_path):
    settings = _settings(tmp_path)
    _seed_schema(settings)
    with TestClient(create_app(settings)) as client:
        missing = client.get("/admin/jobs")
        invalid = client.get(
            "/admin/jobs",
            headers={"Authorization": "Bearer wrong"},
        )
        assert missing.status_code == 401
        assert invalid.status_code == 401
        assert missing.json()["error"]["code"] == "unauthorized"


def test_admin_job_history(tmp_path):
    settings = _settings(tmp_path)
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            IngestionJobRun(
                job_name="senato",
                source_key="senato-repubblica",
                status=IngestionJobStatus.SUCCEEDED,
                trigger_type=IngestionJobTrigger.CLI,
                started_at=datetime(2026, 10, 6, 1, tzinfo=timezone.utc),
                completed_at=datetime(2026, 10, 6, 1, 1, tzinfo=timezone.utc),
                records_processed=10,
                records_created=4,
                records_updated=1,
                records_skipped=5,
                attempt_count=1,
                job_metadata={"fixture": True},
            )
        )
        session.commit()
        run_id = session.scalar(select(IngestionJobRun.id))
    engine.dispose()

    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer test-admin-secret"}
        listing = client.get("/admin/jobs", headers=headers)
        detail = client.get(f"/admin/jobs/{run_id}", headers=headers)
        missing = client.get("/admin/jobs/9999", headers=headers)
        public = client.get("/jobs")

        assert listing.status_code == 200
        payload = listing.json()
        assert payload["total"] == 1
        assert payload["items"][0]["job_name"] == "senato"
        assert payload["items"][0]["status"] == "succeeded"
        assert payload["items"][0]["records_created"] == 4
        assert payload["items"][0]["duration_ms"] is not None
        assert payload["items"][0]["stale_recovered"] is False
        assert "password" not in str(payload).casefold()
        assert detail.status_code == 200
        assert detail.json()["id"] == run_id
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "ingestion_job_not_found"
        assert public.status_code == 404


def test_admin_can_run_job(tmp_path, monkeypatch):
    def fake_runner(runtime, session_factory):
        del runtime, session_factory
        return IngestionJobMetrics(
            records_processed=3,
            records_created=1,
            records_updated=0,
            records_skipped=2,
        )

    catalog = {
        "senato": JobSpec(
            "senato",
            "senato-repubblica",
            fake_runner,
            "schedule_senato_cron",
        )
    }
    monkeypatch.setattr("backend.app.jobs.service.JOB_CATALOG", catalog)
    settings = _settings(tmp_path)
    _seed_schema(settings)
    with TestClient(create_app(settings)) as client:
        headers = {"Authorization": "Bearer test-admin-secret"}
        response = client.post("/admin/jobs/senato/run", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["job_name"] == "senato"
        assert body["status"] == "succeeded"
        assert body["trigger_type"] == "admin"
        assert body["records_processed"] == 3
        unknown = client.post("/admin/jobs/unknown/run", headers=headers)
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "invalid_ingestion_job"
