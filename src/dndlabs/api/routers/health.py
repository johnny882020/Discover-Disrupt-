"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from dndlabs.api.dependencies import Services
from dndlabs.core.exceptions import StorageError
from dndlabs.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    status: str
    database: str


@router.get("/health")
def health() -> HealthResponse:
    """Liveness probe.

    Deliberately does not touch the database: a slow or unmigrated database
    must not make Render (or any platform health check bound to this path)
    restart an otherwise-healthy process. Use ``/health/ready`` to check
    storage.

    Returns:
        ``{"status": "ok"}``.
    """
    return HealthResponse()


@router.get(
    "/health/ready",
    responses={
        503: {
            "model": ReadinessResponse,
            "description": "Database unreachable or not migrated.",
        }
    },
)
def readiness(services: Services, response: Response) -> ReadinessResponse:
    """Readiness probe: liveness plus a real database check.

    Runs a trivial query against the ``organizations`` table. This is what
    would have caught the incident where migrations silently never applied
    and every request failed with ``relation "organizations" does not
    exist`` while ``/health`` kept reporting ok. Not used as the platform's
    liveness path (see ``health``) — for manual/monitoring use.

    Args:
        services: Injected services.
        response: Used to set a 503 status on failure without raising.

    Returns:
        ``{"status": "ok", "database": "ok"}``, or ``status: "unavailable"``
        with a ``503`` on failure. This endpoint is unauthenticated, so the
        underlying database error is logged server-side, not returned in
        the response body.
    """
    try:
        services.repositories.organizations.ping()
    except StorageError:
        logger.warning("readiness_check_failed", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="unavailable", database="unavailable")
    return ReadinessResponse(status="ok", database="ok")
