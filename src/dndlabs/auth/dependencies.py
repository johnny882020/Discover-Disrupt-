"""FastAPI dependency that authenticates a request via ``X-API-Key``."""

from fastapi import Header, Request

from dndlabs.auth.service import AuthService
from dndlabs.core.exceptions import InvalidApiKeyError
from dndlabs.core.schemas import OrgContext


async def get_current_org(
    request: Request, x_api_key: str | None = Header(default=None)
) -> OrgContext:
    """Resolve the authenticated organization for a request.

    Args:
        request: The incoming request (used to reach app-level services).
        x_api_key: The ``X-API-Key`` header value.

    Returns:
        The authenticated org context.

    Raises:
        InvalidApiKeyError: If the key is missing or invalid.
    """
    if x_api_key is None:
        raise InvalidApiKeyError("missing API key")
    auth_service: AuthService = request.app.state.services.auth
    return auth_service.resolve(x_api_key)


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
    if not x_admin_secret or x_admin_secret != expected:
        raise InvalidApiKeyError("missing or invalid admin secret")
