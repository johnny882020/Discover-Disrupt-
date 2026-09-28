"""FastAPI dependencies that authenticate a request.

A request authenticates with either an API key (``X-API-Key``) or a
sign-in session (``Authorization: Bearer <token>``). Both schemes are
declared to OpenAPI, so ``/docs`` offers them under "Authorize".
"""

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from dndlabs.auth.service import AuthService
from dndlabs.core.exceptions import InvalidApiKeyError, NotAuthenticatedError
from dndlabs.core.schemas import OrgContext

_api_key_scheme = APIKeyHeader(
    name="X-API-Key", auto_error=False, description="Organization API key (programmatic access)."
)
_bearer_scheme = HTTPBearer(
    auto_error=False, description="Session token from POST /auth/login (web app users)."
)

#: Bucket name for a request with no client address (e.g. some test
#: transports); such requests share one set of limits.
_UNKNOWN_CLIENT = "unknown"


def client_ip(request: Request) -> str:
    """The IP address the brute-force limits are counted against.

    ``request.client.host`` is the TCP peer, which behind the hosting
    platform's proxy is the proxy itself. The deployment runs uvicorn with
    proxy headers enabled for that proxy only (``--proxy-headers`` and
    ``--forwarded-allow-ips``), so uvicorn replaces the peer with the
    client address the proxy forwarded. ``X-Forwarded-For`` is deliberately
    never read here: any client can send one, and trusting it would let an
    attacker pick a fresh "IP" for every request and escape every per-IP
    limit.

    Args:
        request: The incoming request.

    Returns:
        The client's IP address.
    """
    return request.client.host if request.client else _UNKNOWN_CLIENT


def get_current_org(
    request: Request,
    api_key: Annotated[str | None, Depends(_api_key_scheme)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> OrgContext:
    """Resolve the authenticated organization for a request.

    An API key takes precedence when both credentials are sent. A plain
    ``def`` on purpose: verification does blocking work (Argon2, database),
    so FastAPI runs it in its threadpool rather than on the event loop.

    Args:
        request: The incoming request (used to reach app-level services).
        api_key: The ``X-API-Key`` header value, if any.
        bearer: The ``Authorization: Bearer`` credentials, if any.

    Returns:
        The authenticated org context.

    Raises:
        NotAuthenticatedError: If no valid credential is presented.
        RateLimitedError: If the client IP has too many recent failures.
    """
    auth_service: AuthService = request.app.state.services.auth
    if api_key is not None:
        return auth_service.resolve_api_key(api_key, client_ip(request))
    if bearer is not None:
        return auth_service.resolve_session(bearer.credentials, client_ip(request))
    raise NotAuthenticatedError("missing credentials: send X-API-Key or Authorization: Bearer")


def require_admin_secret(
    request: Request, x_admin_secret: str | None = Header(default=None)
) -> None:
    """Verify the admin bootstrap secret for org/key-provisioning endpoints.

    Args:
        request: The incoming request.
        x_admin_secret: The ``X-Admin-Secret`` header value.

    Raises:
        InvalidApiKeyError: If the secret is missing or does not match.
    """
    expected = request.app.state.services.settings.admin_bootstrap_secret
    # compare_digest: constant-time, so response timing does not reveal how
    # much of a guess matched. On bytes, because on str it raises TypeError
    # for non-ASCII input (a 500 instead of a 401).
    # No configured secret (only possible with injected test services; the
    # app refuses to start without one) opens nothing.
    if (
        expected is None
        or not x_admin_secret
        or not secrets.compare_digest(x_admin_secret.encode(), expected.encode())
    ):
        raise InvalidApiKeyError("missing or invalid admin secret")
