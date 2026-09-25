"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, read from ``DNDLABS_*`` environment variables.

    Attributes:
        database_url: SQLAlchemy URL of the database.
        export_dir: Directory where exported datasets are written.
        log_level: Root log level name.
        log_json: Emit JSON log lines when true, human-readable lines otherwise.
        pubchem_base_url: Base URL of the PubChem PUG REST API.
        pubchem_timeout_seconds: Per-request timeout for PubChem calls.
        pubchem_batch_size: Maximum CIDs per PubChem request.
        pubchem_max_retries: Retries for transient PubChem failures.
        pubchem_backoff_seconds: Initial backoff between retries (doubles each time).
        auto_create_schema: Create missing tables on startup (dev/test convenience).
    """

    model_config = SettingsConfigDict(env_prefix="DNDLABS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dndlabs.db"
    export_dir: Path = Path("./exports")
    log_level: str = "INFO"
    log_json: bool = True
    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    pubchem_timeout_seconds: float = Field(default=30.0, gt=0)
    pubchem_batch_size: int = Field(default=100, ge=1, le=500)
    pubchem_max_retries: int = Field(default=3, ge=0)
    pubchem_backoff_seconds: float = Field(default=0.5, ge=0)
    auto_create_schema: bool = True

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        """Point bare Postgres URLs (as issued by Render/Heroku) at the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url.removeprefix(prefix)
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance.

    Returns:
        The cached :class:`Settings` object.
    """
    return Settings()
