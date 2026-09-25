"""Liveness endpoint (no authentication)."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = "ok"


@router.get("/health")
def health() -> HealthResponse:
    """Liveness probe.

    Returns:
        ``{"status": "ok"}``.
    """
    return HealthResponse()
