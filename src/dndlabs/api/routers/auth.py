"""Self-service auth endpoints: sign-in, sessions, invitations, keys and privacy deletion."""

from fastapi import APIRouter, status

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.exceptions import ForbiddenError
from dndlabs.core.schemas import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationToken,
    LoginRequest,
    OrgContext,
    PasswordChange,
    Role,
    SessionCreated,
)

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
def login(body: LoginRequest, services: Services) -> SessionCreated:
    """Exchange an email and password for a session token.

    Args:
        body: The credentials.
        services: Injected services.

    Returns:
        The session token (send it as ``Authorization: Bearer <token>``),
        its expiry, and the signed-in user.
    """
    return services.auth.login(body.email, body.password)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(org: CurrentOrg, services: Services) -> None:
    """End the calling session. Its token stops working immediately.

    Args:
        org: The authenticated context (must be a user session).
        services: Injected services.
    """
    services.auth.logout(org)


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, org: CurrentOrg, services: Services) -> None:
    """Change the signed-in user's password; their other sessions are ended.

    Args:
        body: Current and new password.
        org: The authenticated context (must be a user session).
        services: Injected services.
    """
    services.auth.change_password(org, body.current_password, body.new_password)


@router.post("/auth/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InvitationCreate, org: CurrentOrg, services: Services
) -> InvitationCreated:
    """Invite someone to the caller's organization (admins and API keys only).

    Args:
        body: Email and role of the invitee.
        org: The authenticated context.
        services: Injected services.

    Returns:
        The invitation, with its single-use token and link. They are shown
        once; deliver the link to the invitee.
    """
    return services.auth.invite(org, body)


@router.post("/auth/invitations/preview")
def preview_invitation(body: InvitationToken, services: Services) -> InvitationPreview:
    """Describe a redeemable invitation without redeeming it.

    Args:
        body: The invitation token.
        services: Injected services.

    Returns:
        The invited email, role and organization.
    """
    invitation, organization = services.auth.preview_invitation(body.token)
    return InvitationPreview(
        email=invitation.email,
        role=invitation.role,
        org_name=organization.name,
        expires_at=invitation.expires_at,
    )


@router.post("/auth/invitations/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(body: InvitationAccept, services: Services) -> SessionCreated:
    """Redeem an invitation by choosing a password; signs the new user in.

    Args:
        body: The invitation token and the chosen password.
        services: Injected services.

    Returns:
        A session for the new account.
    """
    return services.auth.accept_invitation(body.token, body.password)


@router.get("/auth/whoami")
def whoami(org: CurrentOrg) -> OrgContext:
    """Describe the calling principal and its organization.

    Args:
        org: The authenticated org context.

    Returns:
        The org context: organization, principal type, role and, for a
        user session, the user's id and email.
    """
    return org


@router.post("/auth/keys/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(org: CurrentOrg, services: Services) -> None:
    """Revoke the API key used to authenticate this request.

    Args:
        org: The authenticated context (must be an API key).
        services: Injected services.
    """
    services.auth.revoke_key(org)


@router.delete("/orgs/me/data", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_data(org: CurrentOrg, services: Services) -> None:
    """Delete every dataset, run and record belonging to the calling org.

    This is the privacy deletion endpoint: it removes all rows scoped to the
    caller's ``org_id`` (runs, datasets, records, quality reports, feature
    vectors, enrichment results). The organization, its API keys and its
    user accounts are kept, so the caller is not locked out. Irreversible
    and org-wide, so it requires the ``admin`` role.

    Args:
        org: The authenticated org context.
        services: Injected services.

    Raises:
        ForbiddenError: If the caller is not an admin.
    """
    if org.role is not Role.ADMIN:
        raise ForbiddenError("only organization admins can delete the organization's data")
    services.repositories.datasets.delete_org_data(org.org_id)
