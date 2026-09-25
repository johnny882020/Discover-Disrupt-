"""Self-service org endpoints: whoami, key revocation, and privacy deletion."""

from fastapi import APIRouter, status

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.schemas import OrgContext

router = APIRouter(tags=["auth"])


@router.get("/auth/whoami")
def whoami(org: CurrentOrg) -> OrgContext:
    """Resolve the calling API key's organization.

    Args:
        org: The authenticated org context.

    Returns:
        The org context, used by the frontend's key-entry screen.
    """
    return org


@router.post("/auth/keys/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(org: CurrentOrg, services: Services) -> None:
    """Revoke the API key used to authenticate this request.

    Args:
        org: The authenticated org context.
        services: Injected services.
    """
    services.auth.revoke_key(org.org_id, org.api_key_id)


@router.delete("/orgs/me/data", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_data(org: CurrentOrg, services: Services) -> None:
    """Delete every dataset, run and record belonging to the calling org.

    This is the privacy deletion endpoint: it removes all rows scoped to the
    caller's ``org_id`` (runs, datasets, records, quality reports, feature
    vectors, enrichment results). The organization and its API keys are
    kept, so the caller is not locked out.

    Args:
        org: The authenticated org context.
        services: Injected services.
    """
    services.repositories.datasets.delete_org_data(org.org_id)
