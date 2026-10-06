from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ProductionConfigError(ValueError):
    """Raised when production settings are missing or unsafe."""


_WEAK_ADMIN_KEYS = frozenset(
    {
        "changeme",
        "secret",
        "admin",
        "password",
        "test",
        "test-admin-secret",
        "verapolitica-demo-admin",
        "ci-test-key-not-a-secret",
    }
)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


class Settings(BaseSettings):
    """Runtime configuration for VeraPolitica services and API."""

    env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = "sqlite:///./data/verapolitica.db"
    raw_storage_path: Path = Path("./data/raw")
    public_base_url: str = ""
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    forwarded_allow_ips: str = ""
    log_format: str = "text"
    log_level: str = "INFO"
    enable_demo_ui: bool | None = None
    enable_api_docs: bool | None = None
    web_host: str = "0.0.0.0"
    web_port: int = Field(default=8000, ge=1, le=65535)
    web_workers: int = Field(default=2, ge=1, le=8)
    db_pool_size: int = Field(default=5, ge=1, le=32)
    db_max_overflow: int = Field(default=5, ge=0, le=32)
    db_pool_timeout: int = Field(default=30, ge=1, le=120)
    db_pool_recycle: int = Field(default=1800, ge=60, le=7200)
    senato_sparql_endpoint: str = "https://dati.senato.it/sparql"
    senato_legislature: int = Field(default=19, gt=0)
    senato_request_timeout_seconds: float = Field(default=30.0, gt=0)
    senato_proposal_record_limit: int = Field(default=100, ge=1, le=1000)
    camera_sparql_endpoint: str = "https://dati.camera.it/sparql"
    camera_legislature: int = Field(default=19, gt=0)
    camera_request_timeout_seconds: float = Field(default=30.0, gt=0)
    governo_index_url: str = "https://www.governo.it/it/ministri-e-sottosegretari"
    governo_request_timeout_seconds: float = Field(default=30.0, gt=0)
    istat_municipalities_xlsx_url: str = (
        "https://www.istat.it/storage/codici-unita-amministrative/"
        "Elenco-comuni-italiani.xlsx"
    )
    dait_current_mayors_csv_url: str = (
        "https://dait.interno.gov.it/documenti/sindaciincarica.csv"
    )
    territorial_request_timeout_seconds: float = Field(default=60.0, gt=0)
    admin_api_key: SecretStr | None = None
    admin_reviewer_identity: str = Field(
        default="admin-editor",
        min_length=1,
        max_length=200,
    )
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    ai_max_document_bytes: int = Field(default=10_000_000, ge=1, le=50_000_000)
    ai_max_chunk_chars: int = Field(default=4_000, ge=100, le=20_000)
    ai_max_document_chunks: int = Field(default=200, ge=1, le=2_000)
    ai_max_chunks_per_run: int = Field(default=40, ge=1, le=200)
    ai_max_evidence_excerpt_chars: int = Field(default=600, ge=50, le=2_000)
    ai_eval_min_precision: float = Field(default=0.90, ge=0, le=1)
    ai_eval_min_evidence_accuracy: float = Field(default=0.95, ge=0, le=1)
    ai_eval_max_hallucination_rate: float = Field(default=0.05, ge=0, le=1)
    schedule_senato_cron: str = ""
    schedule_camera_cron: str = ""
    schedule_governo_cron: str = ""
    schedule_proposals_cron: str = ""
    schedule_territories_cron: str = ""
    schedule_territorial_offices_cron: str = ""
    schedule_civic_reminders_cron: str = ""
    job_max_retries: int = Field(default=1, ge=0, le=5)
    job_retry_backoff_seconds: float = Field(default=2.0, gt=0, le=60)
    job_stale_after_minutes: int = Field(default=60, ge=5, le=1440)

    @property
    def is_production(self) -> bool:
        return self.env is AppEnvironment.PRODUCTION

    @property
    def scheduler_enabled(self) -> bool:
        return any(
            value.strip()
            for value in (
                self.schedule_senato_cron,
                self.schedule_camera_cron,
                self.schedule_governo_cron,
                self.schedule_proposals_cron,
                self.schedule_territories_cron,
                self.schedule_territorial_offices_cron,
                self.schedule_civic_reminders_cron,
            )
        )

    @property
    def cors_origin_list(self) -> tuple[str, ...]:
        return _csv(self.cors_origins)

    @property
    def trusted_host_list(self) -> tuple[str, ...]:
        return _csv(self.trusted_hosts)

    @property
    def forwarded_allow_ip_list(self) -> tuple[str, ...]:
        return _csv(self.forwarded_allow_ips)

    @property
    def demo_ui_enabled(self) -> bool:
        if self.enable_demo_ui is not None:
            return self.enable_demo_ui
        return not self.is_production

    @property
    def api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return not self.is_production

    @property
    def resolved_log_format(self) -> str:
        value = self.log_format.strip().casefold()
        if value in {"json", "text"}:
            return value
        return "json" if self.is_production else "text"

    @property
    def ai_extraction_enabled(self) -> bool:
        provider = (self.llm_provider or "").strip()
        model = (self.llm_model or "").strip()
        key = self.llm_api_key.get_secret_value() if self.llm_api_key else ""
        return bool(provider and model and key)

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.env is not AppEnvironment.PRODUCTION:
            return self
        errors: list[str] = []
        if not self.database_url.startswith("postgresql"):
            errors.append("production requires VERAPOLITICA_DATABASE_URL to be PostgreSQL")
        key = self.admin_api_key.get_secret_value() if self.admin_api_key else ""
        if len(key) < 24 or key.casefold() in _WEAK_ADMIN_KEYS:
            errors.append(
                "production requires VERAPOLITICA_ADMIN_API_KEY of at least 24 characters"
            )
        if not str(self.raw_storage_path).strip():
            errors.append("production requires VERAPOLITICA_RAW_STORAGE_PATH")
        origins = self.cors_origin_list
        if not origins or "*" in origins:
            errors.append(
                "production requires an explicit VERAPOLITICA_CORS_ORIGINS allowlist"
            )
        hosts = self.trusted_host_list
        if not hosts or "*" in hosts:
            errors.append(
                "production requires an explicit VERAPOLITICA_TRUSTED_HOSTS allowlist"
            )
        provider = (self.llm_provider or "").strip()
        if provider:
            if not (self.llm_model or "").strip():
                errors.append("AI extraction requires VERAPOLITICA_LLM_MODEL")
            if not (self.llm_api_key and self.llm_api_key.get_secret_value().strip()):
                errors.append("AI extraction requires VERAPOLITICA_LLM_API_KEY")
        if errors:
            raise ProductionConfigError("; ".join(errors))
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VERAPOLITICA_",
        extra="ignore",
    )


def configured_environment() -> AppEnvironment:
    """Read only VERAPOLITICA_ENV, including from `.env`, without full validation."""

    class _Probe(BaseSettings):
        env: AppEnvironment = AppEnvironment.DEVELOPMENT
        model_config = SettingsConfigDict(
            env_file=".env",
            env_prefix="VERAPOLITICA_",
            extra="ignore",
        )

    try:
        return _Probe().env
    except ValidationError:
        return AppEnvironment.DEVELOPMENT


@lru_cache
def get_settings() -> Settings:
    return Settings()
