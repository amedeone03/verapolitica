from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import AppEnvironment, ProductionConfigError, Settings
from backend.app.jobs.catalog import enabled_schedules


_PRODUCTION = {
    "env": AppEnvironment.PRODUCTION,
    "database_url": "postgresql+psycopg://verapolitica:x@localhost:5432/verapolitica",
    "admin_api_key": "a-sufficiently-long-admin-token",
    "cors_origins": "https://verapolitica.it",
    "trusted_hosts": "verapolitica.it",
    "public_base_url": "https://verapolitica.it",
    "raw_storage_path": "/var/lib/verapolitica/raw",
}


def test_development_keeps_local_defaults():
    settings = Settings(
        env=AppEnvironment.DEVELOPMENT,
        database_url="sqlite:///./data/verapolitica.db",
        public_base_url="",
        enable_demo_ui=None,
        enable_api_docs=None,
        llm_provider=None,
        llm_model=None,
        schedule_senato_cron="",
        schedule_camera_cron="",
        schedule_governo_cron="",
        schedule_proposals_cron="",
        schedule_territories_cron="",
        schedule_territorial_offices_cron="",
        schedule_civic_reminders_cron="",
        schedule_pledge_evidence_cron="",
        raw_storage_path=Path("./data/raw"),
    )
    assert settings.database_url.startswith("sqlite:")
    assert settings.public_base_url == ""
    assert settings.demo_ui_enabled is True
    assert settings.api_docs_enabled is True
    assert settings.scheduler_enabled is False
    assert settings.ai_extraction_enabled is False
    assert not Path(settings.raw_storage_path).is_absolute()


def test_production_requires_public_base_url():
    with pytest.raises((ProductionConfigError, ValidationError), match="PUBLIC_BASE_URL"):
        Settings(**{**_PRODUCTION, "public_base_url": ""})


def test_production_requires_public_origin_in_cors_and_hosts():
    with pytest.raises((ProductionConfigError, ValidationError), match="CORS_ORIGINS"):
        Settings(
            **{
                **_PRODUCTION,
                "cors_origins": "https://www.verapolitica.it",
            }
        )
    with pytest.raises((ProductionConfigError, ValidationError), match="TRUSTED_HOSTS"):
        Settings(
            **{
                **_PRODUCTION,
                "trusted_hosts": "www.verapolitica.it",
            }
        )


def test_production_requires_absolute_raw_storage_path():
    with pytest.raises((ProductionConfigError, ValidationError), match="absolute path"):
        Settings(**{**_PRODUCTION, "raw_storage_path": "./data/raw"})


def test_production_rejects_demo_storage_paths():
    with pytest.raises((ProductionConfigError, ValidationError), match="demo/local"):
        Settings(
            **{
                **_PRODUCTION,
                "raw_storage_path": "/var/lib/verapolitica/data/demo/raw",
            }
        )


def test_production_rejects_wildcard_forwarded_allow_ips():
    with pytest.raises((ProductionConfigError, ValidationError), match="FORWARDED_ALLOW_IPS"):
        Settings(**{**_PRODUCTION, "forwarded_allow_ips": "*"})


def test_production_rejects_oversized_request_body_limit():
    with pytest.raises((ProductionConfigError, ValidationError), match="MAX_REQUEST_BODY_BYTES"):
        Settings(**{**_PRODUCTION, "max_request_body_bytes": 5_000_000})


def test_production_rejects_demo_ui_and_placeholder_admin_key():
    with pytest.raises((ProductionConfigError, ValidationError), match="ENABLE_DEMO_UI"):
        Settings(**{**_PRODUCTION, "enable_demo_ui": True})
    with pytest.raises((ProductionConfigError, ValidationError), match="ADMIN_API_KEY"):
        Settings(
            **{
                **_PRODUCTION,
                "admin_api_key": "replace-with-a-long-random-secret",
            }
        )


def test_production_does_not_enable_scheduler_or_ai_by_default():
    settings = Settings(**{**_PRODUCTION, "log_format": ""})
    assert settings.is_production
    assert settings.scheduler_enabled is False
    assert settings.ai_extraction_enabled is False
    assert enabled_schedules(settings) == ()
    assert settings.demo_ui_enabled is False
    assert settings.api_docs_enabled is False
    assert settings.resolved_log_format == "json"
    assert "*" not in settings.cors_origin_list
    assert "*" not in settings.trusted_host_list


def test_log_format_defaults_by_environment():
    assert Settings(env=AppEnvironment.DEVELOPMENT, log_format="").resolved_log_format == "text"
    assert Settings(**{**_PRODUCTION, "log_format": ""}).resolved_log_format == "json"
    assert Settings(**{**_PRODUCTION, "log_format": "text"}).resolved_log_format == "text"
