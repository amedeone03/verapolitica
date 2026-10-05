from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for VeraPolitica services and API."""

    database_url: str = "sqlite:///./data/verapolitica.db"
    raw_storage_path: Path = Path("./data/raw")
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VERAPOLITICA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
