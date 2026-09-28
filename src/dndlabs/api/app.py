"""FastAPI application factory.

Builds the app: services and the in-process run worker (tied to the app's
lifespan), CORS, the request body size limit, the domain-error handlers, the
``/api/v1`` routers and the root ``/`` and ``/health`` meta endpoints.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from dndlabs import __version__
from dndlabs.api.dependencies import ApiServices
from dndlabs.api.errors import register_error_handlers
from dndlabs.api.landing import ServiceInfo, render_landing
from dndlabs.api.routers import admin, auth, datasets, enrichment, health, pipelines, uploads
from dndlabs.core.config import get_settings
from dndlabs.core.exceptions import ConfigurationError
from dndlabs.core.logging import configure_logging
from dndlabs.pipeline.factory import build_container

API_PREFIX = "/api/v1"
#: Fixed 413 body, shaped like every other error response (``{"detail": ...}``).
BODY_TOO_LARGE_DETAIL = "request body too large"


class _BodyTooLargeError(Exception):
    """Raised from the wrapped ``receive`` once a body exceeds the limit.

    Private and deliberately not a ``DndLabsError``: no registered handler
    maps it, so it unwinds to :class:`BodySizeLimitMiddleware`, which owns
    the 413. Its message never reaches a client.
    """


class BodySizeLimitMiddleware:
    """Reject request bodies larger than a limit with a fixed 413.

    A pure ASGI middleware (not ``BaseHTTPMiddleware``) so it sees the body
    as the server delivers it, before any handler, form parser or upload
    service buffers it in memory. Two checks:

    * a declared ``Content-Length`` above the limit is refused before the
      application runs at all;
    * bodies without one (``Transfer-Encoding: chunked``) or that lie about
      it are counted chunk by chunk, and the request is aborted with 413 as
      soon as the running total passes the limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: Callable[[], int]) -> None:
        """Wrap an ASGI app.

        Args:
            app: The next ASGI app in the stack.
            max_bytes: Returns the current limit in bytes. Resolved per
                request because the settings that hold it only exist once
                the lifespan has built (or been handed) the services.
        """
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Enforce the limit on HTTP requests; pass everything else through.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes()
        declared = _content_length(scope)
        if declared is not None and declared > limit:
            await _too_large(scope, receive, send)
            return

        received = 0
        exceeded = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            # Once the limit is hit, whatever the app makes of the aborted
            # read (FastAPI turns body-read errors into a 400, a handler
            # might catch it) is dropped: the client gets the 413 below.
            if exceeded:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        with suppress(_BodyTooLargeError):
            await self.app(scope, limited_receive, guarded_send)
        # A response already under way (a handler streaming while it reads)
        # cannot be replaced; its connection just ends. That needs a handler
        # that responds before reading its body, which none here does.
        if exceeded and not response_started:
            await _too_large(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    """Return the request's declared ``Content-Length``, if it is a valid one.

    A malformed header is left to the server's HTTP parser to reject; the
    streamed byte count still bounds the body either way.
    """
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    """Send the fixed 413 response."""
    response = JSONResponse(status_code=413, content={"detail": BODY_TOO_LARGE_DETAIL})
    await response(scope, receive, send)


def _request_max_bytes(app: FastAPI) -> int:
    """Return the body size limit from the services the lifespan installed.

    Read from ``app.state.services`` rather than :func:`get_settings` so
    injected (test) services apply their own settings, just like every route.
    """
    services: ApiServices = app.state.services
    return services.settings.request_max_bytes


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
            # Injected services (tests) are owned by the caller: start/stop
            # their worker if they have one, but never close their storage.
            app.state.services = services
            if services.worker is not None:
                await services.worker.start()
            try:
                yield
            finally:
                if services.worker is not None:
                    await services.worker.stop()
            return
        settings = get_settings()
        configure_logging(settings.log_level, settings.log_json)
        # Fail the start rather than serve /admin with no secret: there is
        # deliberately no default (a published one would open those routes).
        if settings.admin_bootstrap_secret is None:
            raise ConfigurationError(
                "DNDLABS_ADMIN_BOOTSTRAP_SECRET is not set; the API needs it to start"
            )
        container = build_container(settings)
        app.state.services = ApiServices(
            repositories=container.repositories,
            service=container.service,
            exporter=container.exporter,
            auth=container.auth,
            uploads=container.uploads,
            assessment=container.assessment,
            settings=settings,
            worker=container.worker,
        )
        # Runs execute in this process: POST /pipelines/run only queues, so
        # without a started worker queued runs would never leave "pending".
        await container.worker.start()
        try:
            yield
        finally:
            # Stop the worker before closing storage: stop() lets active runs
            # reach a checkpoint and releases their leases, which needs the DB.
            await container.worker.stop()
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

    # Added before CORS so it sits inside it: a 413 still carries the CORS
    # headers, so the browser app sees the status instead of a CORS error.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=lambda: _request_max_bytes(app))

    # Only the configured web-app origin may call the API from a browser; "*"
    # is used only for injected (test) services. No allow_credentials: auth
    # travels in X-API-Key / Authorization headers, never cookies.
    frontend_origin = get_settings().frontend_origin if services is None else "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Includes the catch-all that keeps exception text out of 500 bodies.
    register_error_handlers(app)
    app.include_router(admin.router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(pipelines.router, prefix=API_PREFIX)
    app.include_router(datasets.router, prefix=API_PREFIX)
    app.include_router(enrichment.router, prefix=API_PREFIX)
    app.include_router(uploads.router, prefix=API_PREFIX)
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
