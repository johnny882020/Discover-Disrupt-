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


_GENERIC_500_DETAIL = "internal server error"


async def _internal(_: Request, exc: Exception) -> JSONResponse:
    """Return 500 for other domain errors, logging full detail server-side only.

    The exception's message (e.g. a wrapped ``psycopg`` error) is never put
    in the response body — an earlier version of this handler did that, and
    a real incident showed a raw database error surfacing verbatim in a
    client-visible 500.
    """
    logger.error("request_failed", extra={"error": str(exc), "type": type(exc).__name__})
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": _GENERIC_500_DETAIL}
    )


async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    """Return 500 for any exception that isn't a ``DndLabsError``.

    This is a safety net, not a load-bearing path: every DB-touching code
    path should already go through ``storage.database.SessionFactory``,
    which converts ``SQLAlchemyError`` into ``StorageError`` (handled by
    ``_internal`` above). This exists so an unanticipated bug still returns a
    clean, logged 500 instead of depending on Starlette's default behavior.
    """
    logger.error("unhandled_exception", extra={"type": type(exc).__name__}, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": _GENERIC_500_DETAIL}
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
    app.add_exception_handler(Exception, _unhandled)
