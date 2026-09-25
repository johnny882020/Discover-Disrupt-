"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from dndlabs import __version__
from dndlabs.api.dependencies import ApiServices
from dndlabs.api.errors import register_error_handlers
from dndlabs.api.landing import ServiceInfo, render_landing
from dndlabs.api.routers import admin, auth, datasets, enrichment, health, pipelines
from dndlabs.core.config import get_settings
from dndlabs.core.logging import configure_logging
from dndlabs.pipeline.factory import build_container

API_PREFIX = "/api/v1"


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
            service=container.service,
            exporter=container.exporter,
            auth=container.auth,
            settings=settings,
        )
        try:
            yield
        finally:
            container.close()

    app = FastAPI(
        title="D&D Labs Data Platform API",
        version=__version__,
        description=(
            "Multi-tenant ingestion, validation and enrichment of "
            "model-ready drug-discovery datasets."
        ),
        lifespan=lifespan,
    )

    frontend_origin = get_settings().frontend_origin if services is None else "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(pipelines.router, prefix=API_PREFIX)
    app.include_router(datasets.router, prefix=API_PREFIX)
    app.include_router(enrichment.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"])
    def root_health() -> dict[str, str]:
        """Liveness probe at the bare root path, for platform health checks.

        Returns:
            ``{"status": "ok"}``.
        """
        return {"status": "ok"}

    @app.get("/", tags=["meta"], response_model=ServiceInfo)
    def landing(request: Request) -> ServiceInfo | HTMLResponse:
        """Describe the service and where to find its documentation.

        Browsers (``Accept: text/html``) get an HTML landing page; every
        other client gets JSON.

        Args:
            request: Incoming request, used for content negotiation.

        Returns:
            Name, version, documentation links and available endpoints.
        """
        info = ServiceInfo(
            name=app.title,
            version=app.version,
            docs=app.docs_url or "/openapi.json",
            health="/health",
            endpoints=_public_endpoints(app),
        )
        if "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(render_landing(info, app.description))
        return info

    return app
