"""Mapping of domain exceptions to HTTP responses."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from dndlabs.core.exceptions import DndLabsError, IngestionError, InvalidApiKeyError, NotFoundError
from dndlabs.core.logging import get_logger

logger = get_logger(__name__)


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    """Return 404 for missing entities."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _unauthorized(_: Request, exc: Exception) -> JSONResponse:
    """Return 401 for missing/invalid/revoked API keys."""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "ApiKey"},
    )


async def _bad_input(_: Request, exc: Exception) -> JSONResponse:
    """Return 422 for inputs a connector could not use."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
    )


async def _internal(_: Request, exc: Exception) -> JSONResponse:
    """Return 500 for other domain errors, logging them."""
    logger.error("request failed", extra={"error": str(exc), "type": type(exc).__name__})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc)}
    )


def register_error_handlers(app: FastAPI) -> None:
    """Attach domain exception handlers to ``app``.

    Args:
        app: The FastAPI application.
    """
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(InvalidApiKeyError, _unauthorized)
    app.add_exception_handler(IngestionError, _bad_input)
    app.add_exception_handler(DndLabsError, _internal)
