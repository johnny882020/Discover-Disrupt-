"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, read from ``DNDLABS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="DNDLABS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dndlabs.db"
    export_dir: Path = Path("./exports")
    log_level: str = "INFO"
    log_json: bool = True
    auto_create_schema: bool = True

    admin_bootstrap_secret: str = "change-me-in-production"
    frontend_origin: str = "http://localhost:5173"

    free_tier_shared_password: str | None = Field(
        default="freetier2026",
        description=(
            "Temporary, insecure shared credential: authenticates as one fixed "
            "org with no per-org key and no database lookup. Set to an empty "
            "string to disable. Replace with real per-org keys before "
            "onboarding real customers."
        ),
    )

    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    pubchem_timeout_seconds: float = Field(default=30.0, gt=0)
    pubchem_batch_size: int = Field(default=100, ge=1, le=500)
    pubchem_max_retries: int = Field(default=3, ge=0)
    pubchem_backoff_seconds: float = Field(default=0.5, ge=0)

    chembl_base_url: str = "https://www.ebi.ac.uk/chembl/api/data"
    chembl_timeout_seconds: float = Field(default=30.0, gt=0)
    chembl_page_size: int = Field(default=50, ge=1, le=1000)
    chembl_max_retries: int = Field(default=3, ge=0)

    nvidia_nim_api_key: str | None = None
    nvidia_nim_base_url: str = "https://health.api.nvidia.com/v1/biology/nvidia/genmol"
    nvidia_nim_timeout_seconds: float = Field(default=60.0, gt=0)
    nvidia_nim_num_candidates: int = Field(default=5, ge=1, le=50)
    nvidia_nim_scoring: str = "QED"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, url: str) -> str:
        """Point bare Postgres URLs (as issued by Render) at the psycopg 3 driver."""
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
