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
    camera_sparql_endpoint: str = "https://dati.camera.it/sparql"
    camera_legislature: int = Field(default=19, gt=0)
    camera_request_timeout_seconds: float = Field(default=30.0, gt=0)
    governo_index_url: str = "https://www.governo.it/it/ministri-e-sottosegretari"
    governo_request_timeout_seconds: float = Field(default=30.0, gt=0)
    admin_api_key: SecretStr | None = None
    admin_reviewer_identity: str = Field(
        default="admin-editor",
        min_length=1,
        max_length=200,
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VERAPOLITICA_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
