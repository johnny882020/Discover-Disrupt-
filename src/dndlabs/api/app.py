"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from dndlabs import __version__
from dndlabs.api.dependencies import ApiServices
from dndlabs.api.errors import register_error_handlers
from dndlabs.api.routers import datasets, pipelines
from dndlabs.core.config import get_settings
from dndlabs.core.logging import configure_logging
from dndlabs.pipeline.factory import build_container


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"


class ServiceInfo(BaseModel):
    """Service description returned at the API root."""

    name: str
    version: str
    docs: str
    health: str
    endpoints: list[str]


def _public_endpoints(app: FastAPI) -> list[str]:
    """List ``METHOD /path`` for every route in the app's OpenAPI schema."""
    paths: dict[str, dict[str, object]] = app.openapi().get("paths", {})
    return [
        f"{method.upper()} {path}" for path, operations in paths.items() for method in operations
    ]


def create_app(services: ApiServices | None = None) -> FastAPI:
    """Create the API application.

    Args:
        services: Pre-built services (tests). When omitted, services are built
            from :class:`~dndlabs.core.config.Settings` at startup and released
            at shutdown.

    Returns:
        The FastAPI app.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Build services on startup and release them on shutdown."""
        if services is not None:
            app.state.services = services
            yield
            return
        settings = get_settings()
        configure_logging(settings.log_level, settings.log_json)
        container = build_container(settings)
        app.state.services = ApiServices(
            repositories=container.repositories,
            runner=container.service,
            renderer=container.exporter,
        )
        try:
            yield
        finally:
            container.close()

    app = FastAPI(
        title="D&D Labs Data API",
        version=__version__,
        description="Ingest, validate and serve model-ready drug-discovery datasets.",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(pipelines.router)
    app.include_router(datasets.router)

    @app.get("/health", tags=["meta"])
    def health() -> HealthResponse:
        """Liveness probe.

        Returns:
            ``{"status": "ok"}``.
        """
        return HealthResponse()

    @app.get("/", tags=["meta"])
    def root() -> ServiceInfo:
        """Describe the service and where to find its documentation.

        Returns:
            Name, version, documentation links and available endpoints.
        """
        return ServiceInfo(
            name=app.title,
            version=app.version,
            docs=app.docs_url or "/openapi.json",
            health="/health",
            endpoints=_public_endpoints(app),
        )

    return app
