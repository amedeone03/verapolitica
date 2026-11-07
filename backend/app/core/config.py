from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
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
        "replace-with-a-long-random-secret",
    }
)

# Local demo only: never accepted in production (see validate_production_settings).
DEMO_REDAZIONE_MEMBERS: dict[str, str] = {
    "demo-redattore": "Redattore demo",
    "demo-verificatore": "Verificatore demo",
    "demo-caporedattore": "Caporedattore demo",
}

# Used only when VERAPOLITICA_SESSION_SECRET is blank outside production.
_DEV_SESSION_SECRET = "dev-session-secret-not-for-production-use!!"

_DEMO_STORAGE_MARKERS = ("/ceo_demo/", "/unified_demo/", "/data/demo/")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _is_demo_storage_path(path: Path) -> bool:
    normalized = f"/{path.as_posix().casefold().strip('/')}/"
    return any(marker in normalized for marker in _DEMO_STORAGE_MARKERS)


def _public_origin(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").casefold()
    if not host:
        return None
    return f"{parsed.scheme}://{parsed.netloc}", host


class Settings(BaseSettings):
    """Runtime configuration for VeraPolitica services and API."""

    env: AppEnvironment = AppEnvironment.DEVELOPMENT
    database_url: str = "sqlite:///./data/verapolitica.db"
    raw_storage_path: Path = Path("./data/raw")
    public_base_url: str = ""
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    forwarded_allow_ips: str = ""
    max_request_body_bytes: int = Field(default=1_048_576, ge=65_536, le=52_428_800)
    # Redazione image uploads only (/redazione/api/immagini): the console already
    # shrinks files before sending; the server compresses them again (images.py).
    max_image_upload_bytes: int = Field(default=4_194_304, ge=65_536, le=16_777_216)
    log_format: str = ""
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
    camera_history_legislatures: str = Field(default="1-19", pattern=r"^\d+(-\d+)?(,\d+(-\d+)?)*$")
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
    # Redazione members: "Nome Cognome=token;Nome Cognome=token". Each member
    # signs in with their own token, so the log knows who wrote and who verified.
    redazione_members: SecretStr | None = None
    # Admin della redazione: member names, separated by ';' or ','. An admin
    # writes and publishes at once and publishes what others write. When no
    # admin is named, any second member verifies (the old four-eyes rule).
    # VERAPOLITICA_REDAZIONE_LEADS is the previous name and still works.
    redazione_admins: str | None = None
    redazione_leads: str | None = None
    # Signs citizen session cookies. Required in production; a local fallback
    # is used only outside production when this is blank.
    session_secret: SecretStr | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    ollama_base_url: str = "http://127.0.0.1:11434"
    ai_max_document_bytes: int = Field(default=50_000_000, ge=1, le=100_000_000)
    demo_upload_path: Path = Path("./data/ceo_demo/uploads")
    portraits_path: Path | None = None
    ai_max_chunk_chars: int = Field(default=4_000, ge=100, le=20_000)
    ai_max_document_chunks: int = Field(default=4_000, ge=1, le=10_000)
    ai_max_chunks_per_run: int = Field(default=40, ge=1, le=200)
    ai_max_selected_chunks: int = Field(default=16, ge=4, le=40)
    ai_max_document_tokens: int = Field(default=4_500, ge=500, le=20_000)
    ai_max_evidence_excerpt_chars: int = Field(default=600, ge=50, le=2_000)
    ollama_num_ctx: int = Field(default=8_192, ge=2_048, le=32_768)
    ollama_structured_format: str = "json"
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
    schedule_pledge_evidence_cron: str = ""
    schedule_camera_history_cron: str = ""
    job_max_retries: int = Field(default=1, ge=0, le=5)
    job_retry_backoff_seconds: float = Field(default=2.0, gt=0, le=60)
    job_stale_after_minutes: int = Field(default=60, ge=5, le=1440)

    @field_validator("database_url", mode="before")
    @classmethod
    def use_psycopg_driver(cls, value: object) -> object:
        """Accept Render's internal postgres:// URL with the installed driver."""

        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator("ollama_structured_format")
    @classmethod
    def normalize_ollama_structured_format(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized in {"json_schema", "schema"}:
            return "json_schema"
        if normalized == "json":
            return "json"
        raise ValueError("ollama_structured_format must be json_schema or json")

    @property
    def camera_history_legislature_numbers(self) -> tuple[int, ...]:
        numbers: set[int] = set()
        for part in self.camera_history_legislatures.split(","):
            low, _, high = part.partition("-")
            numbers.update(range(int(low), int(high or low) + 1))
        return tuple(sorted(number for number in numbers if number >= 1))

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
                self.schedule_pledge_evidence_cron,
                self.schedule_camera_history_cron,
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
        provider = (self.llm_provider or "").strip().casefold()
        model = (self.llm_model or "").strip()
        if not provider or not model:
            return False
        if provider == "ollama":
            return bool(self.ollama_base_url.strip())
        key = self.llm_api_key.get_secret_value() if self.llm_api_key else ""
        return bool(key)

    @property
    def session_signing_key(self) -> str:
        raw = self.session_secret.get_secret_value() if self.session_secret else ""
        if raw.strip():
            return raw.strip()
        return "" if self.is_production else _DEV_SESSION_SECRET

    @property
    def redazione_member_tokens(self) -> dict[str, str]:
        """Token -> member name. Local demos get three documented demo members."""

        raw = self.redazione_members.get_secret_value() if self.redazione_members else ""
        members: dict[str, str] = {}
        for chunk in raw.replace("\n", ";").split(";"):
            name, separator, token = chunk.partition("=")
            if separator and name.strip() and token.strip():
                members[token.strip()] = name.strip()
        if not members and not self.is_production and self.demo_ui_enabled:
            return dict(DEMO_REDAZIONE_MEMBERS)
        return members

    @property
    def redazione_lead_names(self) -> frozenset[str]:
        """Admin names. Only names that are members count."""

        names = set(self.redazione_member_tokens.values())
        raw = self.redazione_admins or self.redazione_leads or ""
        if not raw.strip() and names == set(DEMO_REDAZIONE_MEMBERS.values()):
            return frozenset({"Caporedattore demo"})
        wanted = {part.strip() for part in raw.replace(",", ";").split(";") if part.strip()}
        return frozenset(wanted & names)

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
        storage = Path(self.raw_storage_path)
        if not str(storage).strip():
            errors.append("production requires VERAPOLITICA_RAW_STORAGE_PATH")
        elif not storage.is_absolute():
            errors.append(
                "production requires VERAPOLITICA_RAW_STORAGE_PATH to be an absolute path"
            )
        elif _is_demo_storage_path(storage):
            errors.append(
                "production VERAPOLITICA_RAW_STORAGE_PATH must not use a demo/local data path"
            )
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
        public = _public_origin(self.public_base_url)
        if public is None:
            errors.append(
                "production requires VERAPOLITICA_PUBLIC_BASE_URL as an absolute http(s) URL"
            )
        else:
            origin, host = public
            if "*" not in origins and origin not in origins:
                errors.append(
                    "production VERAPOLITICA_PUBLIC_BASE_URL origin must be listed in "
                    "VERAPOLITICA_CORS_ORIGINS"
                )
            hosts_folded = {item.casefold() for item in hosts}
            if "*" not in hosts and host not in hosts_folded:
                errors.append(
                    "production VERAPOLITICA_PUBLIC_BASE_URL host must be listed in "
                    "VERAPOLITICA_TRUSTED_HOSTS"
                )
        if "*" in self.forwarded_allow_ip_list:
            errors.append(
                "production must not set VERAPOLITICA_FORWARDED_ALLOW_IPS to *"
            )
        if self.max_request_body_bytes > 2_097_152:
            errors.append(
                "production VERAPOLITICA_MAX_REQUEST_BODY_BYTES must be <= 2097152"
            )
        if self.enable_demo_ui is True:
            errors.append("production must not enable VERAPOLITICA_ENABLE_DEMO_UI")
        session = self.session_secret.get_secret_value() if self.session_secret else ""
        if (
            len(session) < 32
            or session.casefold() in _WEAK_ADMIN_KEYS
            or session == _DEV_SESSION_SECRET
            or (key and session == key)
        ):
            errors.append(
                "production requires VERAPOLITICA_SESSION_SECRET of at least 32 characters"
            )
        for token in self.redazione_member_tokens:
            if len(token) < 24 or token in DEMO_REDAZIONE_MEMBERS:
                errors.append(
                    "production VERAPOLITICA_REDAZIONE_MEMBERS tokens must be at least 24 characters"
                )
                break
        provider = (self.llm_provider or "").strip().casefold()
        if provider:
            if not (self.llm_model or "").strip():
                errors.append("AI extraction requires VERAPOLITICA_LLM_MODEL")
            if provider == "openai" and not (
                self.llm_api_key and self.llm_api_key.get_secret_value().strip()
            ):
                errors.append("AI extraction requires VERAPOLITICA_LLM_API_KEY")
            if provider not in {"openai", "ollama"}:
                errors.append("AI extraction provider must be openai or ollama")
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
