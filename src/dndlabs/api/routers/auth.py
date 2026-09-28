"""Self-service auth endpoints: sign-in, sessions, invitations, keys and privacy deletion."""

import uuid

from fastapi import APIRouter, Request, status

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.auth.dependencies import client_ip
from dndlabs.core.exceptions import ForbiddenError
from dndlabs.core.schemas import (
    Invitation,
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationPreview,
    InvitationToken,
    LoginRequest,
    MemberUpdate,
    OrgContext,
    PasswordChange,
    PasswordResetCreated,
    PasswordResetPreview,
    Role,
    SessionCreated,
    User,
)

router = APIRouter(tags=["auth"])


# Unauthenticated routes in this module: login, and the invitation and
# password-reset preview/accept pairs, which authenticate by their single-use
# token. Every other route resolves the caller through ``CurrentOrg``.


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, services: Services) -> SessionCreated:
    """Exchange an email and password for a session token.

    Limited per client IP and per email (``429`` with ``Retry-After``).

    Args:
        body: The credentials.
        request: The incoming request (its client IP is rate-limited).
        services: Injected services.

    Returns:
        The session token (send it as ``Authorization: Bearer <token>``),
        its expiry, and the signed-in user.
    """
    return services.auth.login(body.email, body.password, client_ip(request))


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

    A POST with the token in the body (not a GET with it in the query) keeps
    the token out of URLs and access logs.

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


@router.get("/auth/invitations")
def list_invitations(org: CurrentOrg, services: Services) -> list[Invitation]:
    """List the organization's pending invitations (admins and API keys only).

    Args:
        org: The authenticated context.
        services: Injected services.

    Returns:
        Invitations that can still be accepted, newest first. Tokens are
        never included.
    """
    return services.auth.list_pending_invitations(org)


@router.delete("/auth/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, org: CurrentOrg, services: Services) -> None:
    """Revoke a pending invitation; its link stops working (admins and API keys only).

    Args:
        invitation_id: The invitation.
        org: The authenticated context.
        services: Injected services.
    """
    services.auth.revoke_invitation(org, invitation_id)


@router.get("/auth/members")
def list_members(org: CurrentOrg, services: Services) -> list[User]:
    """List the organization's user accounts (admins and API keys only).

    Args:
        org: The authenticated context.
        services: Injected services.

    Returns:
        The members, oldest first.
    """
    return services.auth.list_members(org)


@router.patch("/auth/members/{user_id}")
def update_member(
    user_id: uuid.UUID, body: MemberUpdate, org: CurrentOrg, services: Services
) -> User:
    """Change a member's role (admins and API keys only).

    Args:
        user_id: The member.
        body: The new role.
        org: The authenticated context.
        services: Injected services.

    Returns:
        The updated member.
    """
    return services.auth.set_member_role(org, user_id, body.role)


@router.delete("/auth/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, org: CurrentOrg, services: Services) -> None:
    """Remove a member; their account and sessions are deleted (admins and API keys only).

    Args:
        user_id: The member.
        org: The authenticated context.
        services: Injected services.
    """
    services.auth.remove_member(org, user_id)


@router.post("/auth/members/{user_id}/password-reset", status_code=status.HTTP_201_CREATED)
def issue_password_reset(
    user_id: uuid.UUID, org: CurrentOrg, services: Services
) -> PasswordResetCreated:
    """Issue a single-use password-reset link for a member (admins and API keys only).

    Args:
        user_id: The member.
        org: The authenticated context.
        services: Injected services.

    Returns:
        The reset token and link, shown once. Earlier unused links for this
        member stop working.
    """
    return services.auth.issue_password_reset(org, user_id)


@router.post("/auth/password-reset/preview")
def preview_password_reset(body: InvitationToken, services: Services) -> PasswordResetPreview:
    """Describe a redeemable password-reset link without redeeming it.

    Args:
        body: The reset token.
        services: Injected services.

    Returns:
        The account's email and organization.
    """
    reset, organization = services.auth.preview_password_reset(body.token)
    return PasswordResetPreview(
        email=reset.email, org_name=organization.name, expires_at=reset.expires_at
    )


@router.post("/auth/password-reset/accept")
def reset_password(body: InvitationAccept, services: Services) -> SessionCreated:
    """Redeem a password-reset link with a new password; signs the user in.

    All of the user's other sessions end. The body reuses
    ``InvitationAccept`` because a reset token is stored as an invitation
    with purpose ``password_reset`` (same ``token`` + ``password`` shape).

    Args:
        body: The reset token and the new password.
        services: Injected services.

    Returns:
        A new session.
    """
    return services.auth.reset_password(body.token, body.password)


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
    # 403, not 404: the caller is inside its own tenant, only its role is short.
    if org.role is not Role.ADMIN:
        raise ForbiddenError("only organization admins can delete the organization's data")
    services.repositories.datasets.delete_org_data(org.org_id)
