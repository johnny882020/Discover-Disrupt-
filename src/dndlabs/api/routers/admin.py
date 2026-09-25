"""Org and API-key bootstrap endpoints (admin-secret protected, not customer-facing)."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dndlabs.api.dependencies import Services
from dndlabs.auth.dependencies import require_admin_secret
from dndlabs.core.schemas import ApiKeyCreated, Organization

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_secret)])


class CreateOrgRequest(BaseModel):
    """Request body for creating an organization."""

    name: str


@router.post("/orgs", status_code=201)
def create_org(body: CreateOrgRequest, services: Services) -> ApiKeyCreated:
    """Create an organization and issue its first API key.

    Args:
        body: The organization's name.
        services: Injected services.

    Returns:
        The one-time reveal of the new key. It is never shown again — the
        caller (an operator, via the admin secret) must record it now.
    """
    org = services.repositories.organizations.create(Organization(name=body.name))
    return services.auth.issue_key(org)


@router.post("/orgs/{org_id}/keys", status_code=201)
def issue_key(org_id: uuid.UUID, services: Services) -> ApiKeyCreated:
    """Issue an additional API key for an existing organization.

    Args:
        org_id: Organization identifier.
        services: Injected services.

    Returns:
        The one-time reveal of the new key.

    Raises:
        NotFoundError: If the organization does not exist.
    """
    org = services.repositories.organizations.get(org_id)
    return services.auth.issue_key(org)
