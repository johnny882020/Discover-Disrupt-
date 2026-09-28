"""Mapping of domain exceptions to HTTP responses.

Every 4xx message below is written for the client by the code that raises
it; 500s never carry the exception's message.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from dndlabs.core.exceptions import (
    ConflictError,
    DndLabsError,
    ForbiddenError,
    IngestionError,
    InvalidCredentialsError,
    InvitationInvalidError,
    NotAuthenticatedError,
    NotFoundError,
    PasswordPolicyError,
    RateLimitedError,
)
from dndlabs.core.logging import get_logger

logger = get_logger(__name__)


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    """Return 404 for missing entities.

    Repositories filter every lookup by the caller's ``org_id``, so another
    organization's entity surfaces here too: a 404 rather than a 403, which
    would confirm that the id exists in some other tenant.
    """
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _unauthorized(_: Request, exc: Exception) -> JSONResponse:
    """Return 401 for a missing/invalid credential or a failed sign-in."""
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
    )


_RATE_LIMITED_DETAIL = "too many attempts; try again later"


async def _rate_limited(_: Request, exc: Exception) -> JSONResponse:
    """Return 429 with ``Retry-After`` when a brute-force limit refuses a request.

    The body is fixed, never the exception's message: which limit refused
    (client IP, email, or email and IP) must not reach the client, since
    that could tell an attacker which emails others are targeting.
    Registered for ``RateLimitedError`` only; the 60-second fallback just
    satisfies the generic ``Exception`` handler signature.
    """
    retry_after = exc.retry_after_seconds if isinstance(exc, RateLimitedError) else 60
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": _RATE_LIMITED_DETAIL},
        headers={"Retry-After": str(retry_after)},
    )


def _status(code: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Build a handler returning ``code`` with the exception's (client-safe) message."""

    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    return handler


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

    Starlette picks the handler registered for the nearest class in the
    exception's MRO, so the specific mappings win over the ``DndLabsError``
    and ``Exception`` fallbacks regardless of registration order (e.g.
    ``InvalidApiKeyError`` is a ``NotAuthenticatedError`` and gets a 401;
    a ``StorageError`` other than ``NotFoundError`` gets the generic 500).

    Args:
        app: The FastAPI application.
    """
    app.add_exception_handler(NotFoundError, _not_found)
    app.add_exception_handler(NotAuthenticatedError, _unauthorized)
    app.add_exception_handler(InvalidCredentialsError, _unauthorized)
    app.add_exception_handler(RateLimitedError, _rate_limited)
    app.add_exception_handler(ForbiddenError, _status(status.HTTP_403_FORBIDDEN))
    app.add_exception_handler(ConflictError, _status(status.HTTP_409_CONFLICT))
    app.add_exception_handler(InvitationInvalidError, _status(status.HTTP_400_BAD_REQUEST))
    app.add_exception_handler(PasswordPolicyError, _status(status.HTTP_422_UNPROCESSABLE_CONTENT))
    app.add_exception_handler(IngestionError, _bad_input)
    app.add_exception_handler(DndLabsError, _internal)
    app.add_exception_handler(Exception, _unhandled)
