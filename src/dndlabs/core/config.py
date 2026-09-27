"""Application configuration: the one place runtime settings are read.

Every tunable comes from a ``DNDLABS_*`` environment variable (or ``.env``)
through :class:`Settings`; no other module reads the environment. Defaults
suit local development, except the admin bootstrap secret, which has none:
the API refuses to start without one (``api/app.py``).
"""

from functools import lru_cache
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Shortest admin bootstrap secret accepted (``secrets.token_urlsafe(32)``
#: gives 43 characters).
ADMIN_SECRET_MIN_LENGTH = 24


class Settings(BaseSettings):
    """All runtime configuration, read from ``DNDLABS_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="DNDLABS_", env_file=".env", extra="ignore")

    # SQLite by default so a checkout runs with no services; deployments
    # point this at Postgres.
    database_url: str = "sqlite:///./dndlabs.db"
    log_level: str = "INFO"
    log_json: bool = True
    #: ``True`` (development): build tables with ``create_all`` and skip the
    #: readiness check's migration-revision test. Deployments set it to
    #: ``false`` so Alembic owns the schema and readiness requires its head.
    auto_create_schema: bool = True

    #: Opens the /admin routes (provision orgs, keys, invitations and resets
    #: for any org). No default: a published placeholder would open them to
    #: anyone, so the API refuses to start without one (the CLI never needs
    #: it). Generate it, e.g. ``python -c "import secrets;
    #: print(secrets.token_urlsafe(32))"``; render.yaml generates one.
    admin_bootstrap_secret: str | None = Field(default=None, min_length=ADMIN_SECRET_MIN_LENGTH)
    #: The web app's origin: the only CORS origin allowed, and the base of
    #: invitation and password-reset links.
    frontend_origin: str = "http://localhost:5173"

    # Bounds keep a misconfiguration from producing never-expiring
    # credentials: sessions and invitations last at most 30 days, reset
    # links at most a week, and passwords can't be configured below 8 chars.
    session_ttl_hours: int = Field(default=12, ge=1, le=720)
    invitation_ttl_hours: int = Field(default=72, ge=1, le=720)
    password_reset_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_min_length: int = Field(default=12, ge=8, le=64)

    #: Brute-force limits (docs/architecture.md#auth), counted per fixed
    #: window in the database so they hold across workers, instances and
    #: restarts. Sign-in counts attempts per client IP, per email and IP,
    #: and per email across all IPs; a successful sign-in is not counted.
    #: API-key and session authentication count failures per client IP.
    #: Bounded so a misconfiguration can neither disable a limit (0) nor
    #: make it meaningless.
    rate_limit_window_seconds: int = Field(default=900, ge=60, le=86_400)
    signin_limit_per_ip: int = Field(default=20, ge=1, le=10_000)
    signin_limit_per_email_and_ip: int = Field(default=5, ge=1, le=1_000)
    signin_limit_per_email: int = Field(default=50, ge=1, le=10_000)
    auth_failure_limit_per_ip: int = Field(default=50, ge=1, le=10_000)

    # Uploads are held in memory and stored in the database, so both size
    # and row count are capped.
    upload_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1024)
    #: Largest request body the API accepts, checked before the body is read
    #: (the upload limit is only checked once a multipart body has been
    #: received). Must leave room above ``upload_max_bytes`` for multipart
    #: framing.
    request_max_bytes: int = Field(default=26 * 1024 * 1024, ge=1024)
    upload_max_rows: int = Field(default=100_000, ge=1)
    #: Distinct identifiers (InChIKey, CID, ChEMBL ID, name) looked up per run;
    #: records beyond it are reported unresolved (0 disables lookups).
    structure_lookup_limit: int = Field(default=1000, ge=0)

    #: Run worker (in the API process): poll interval when idle, lease length
    #: (renewed every third of it), how many times a run's worker may stop
    #: unexpectedly (crash, kill, hang: its lease expired) before the run
    #: fails, runs executed at once, and how long shutdown waits for runs to
    #: stop. A clean shutdown hands its runs back and never counts.
    worker_poll_seconds: float = Field(default=2.0, gt=0)
    worker_lease_seconds: float = Field(default=120.0, ge=10)
    worker_max_lost_leases: int = Field(default=3, ge=1)
    worker_concurrency: int = Field(default=1, ge=1, le=8)
    worker_shutdown_grace_seconds: float = Field(default=20.0, ge=0)

    pubchem_base_url: str = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
    pubchem_timeout_seconds: float = Field(default=30.0, gt=0)
    pubchem_batch_size: int = Field(default=100, ge=1, le=500)
    pubchem_max_retries: int = Field(default=3, ge=0)
    pubchem_backoff_seconds: float = Field(default=0.5, ge=0)
    #: Pause between PubChem requests: PubChem allows at most 5 per second.
    pubchem_min_interval_seconds: float = Field(default=0.2, ge=0)

    chembl_base_url: str = "https://www.ebi.ac.uk/chembl/api/data"
    chembl_timeout_seconds: float = Field(default=30.0, gt=0)
    chembl_page_size: int = Field(default=50, ge=1, le=1000)
    chembl_max_retries: int = Field(default=3, ge=0)
    chembl_backoff_seconds: float = Field(default=0.5, ge=0)

    # No key means enrichment is skipped (NullEnrichmentClient), not failed.
    nvidia_nim_api_key: str | None = None
    nvidia_nim_base_url: str = "https://health.api.nvidia.com/v1/biology/nvidia/genmol"
    nvidia_nim_timeout_seconds: float = Field(default=60.0, gt=0)
    nvidia_nim_num_candidates: int = Field(default=5, ge=1, le=50)
    nvidia_nim_scoring: str = "QED"

    @field_validator("admin_bootstrap_secret", mode="before")
    @classmethod
    def _empty_secret_is_unset(cls, value: object) -> object:
        """Read an empty variable (``DNDLABS_ADMIN_BOOTSTRAP_SECRET=``) as unset."""
        return None if value == "" else value

    @model_validator(mode="after")
    def _request_limit_covers_uploads(self) -> Self:
        """Reject a request limit that would refuse a maximum-size upload."""
        if self.request_max_bytes <= self.upload_max_bytes:
            raise ValueError("request_max_bytes must exceed upload_max_bytes")
        return self

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
