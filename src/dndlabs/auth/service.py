"""Authentication: API keys, user sign-in sessions and invitations.

Two kinds of principal authenticate a request, both resolved to an
:class:`~dndlabs.core.schemas.OrgContext`:

- **API keys** (``X-API-Key``) for programmatic access. Argon2-hashed,
  looked up by a non-secret prefix, and acting with the ``admin`` role.
- **User sessions** (``Authorization: Bearer ddl_sess_…``) for people using
  the web app. A user joins an organization by redeeming a single-use
  invitation, choosing their own password; signing in exchanges the email
  and password for an opaque, expiring, revocable session token.

See docs/architecture.md#auth.
"""

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dndlabs.auth.models import generate_key, hash_key, key_prefix, verify_key
from dndlabs.auth.passwords import (
    check_password_policy,
    hash_password,
    needs_rehash,
    verify_against_dummy,
    verify_password,
)
from dndlabs.auth.tokens import (
    INVITATION_TOKEN_PREFIX,
    SESSION_TOKEN_PREFIX,
    new_token,
    token_digest,
)
from dndlabs.core.exceptions import (
    AccountLockedError,
    AuthError,
    ConflictError,
    ForbiddenError,
    InvalidApiKeyError,
    InvalidCredentialsError,
    InvitationInvalidError,
    NotAuthenticatedError,
    NotFoundError,
)
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    ApiKeyCreated,
    Invitation,
    InvitationCreate,
    InvitationCreated,
    Organization,
    OrgContext,
    PrincipalType,
    Role,
    SessionCreated,
    User,
    UserSession,
    normalize_email,
    utcnow,
)

logger = get_logger(__name__)

#: How many times ``issue_key`` retries after an (unlikely) prefix collision.
_KEY_ISSUE_ATTEMPTS = 5
#: Expired sessions are kept this long (for audit) before housekeeping deletes them.
_EXPIRED_SESSION_RETENTION = timedelta(days=30)

_INVALID_CREDENTIALS = "invalid email or password"
_INVALID_SESSION = "invalid or expired session"
_INVALID_INVITATION = "invitation is invalid, expired or already used"


@dataclass(frozen=True)
class AuthPolicy:
    """Tunable parameters of user authentication.

    Attributes:
        session_ttl: Absolute lifetime of a sign-in session.
        invitation_ttl: How long an invitation can be redeemed.
        max_login_attempts: Consecutive failed sign-ins that lock an account.
        lockout: How long a lock lasts.
        password_min_length: Minimum password length.
        frontend_origin: Web app origin; invitation links point here.
        clock: Current-time source (injectable for tests).
    """

    session_ttl: timedelta = timedelta(hours=12)
    invitation_ttl: timedelta = timedelta(hours=72)
    max_login_attempts: int = 5
    lockout: timedelta = timedelta(minutes=15)
    password_min_length: int = 12
    frontend_origin: str = "http://localhost:5173"
    clock: Callable[[], datetime] = field(default=utcnow)


class AuthService:
    """Issues and verifies credentials against the auth repositories."""

    def __init__(self, repositories: Repositories, policy: AuthPolicy | None = None) -> None:
        """Create the service.

        Args:
            repositories: Repository bundle (organizations, API keys, users,
                sessions and invitations are used).
            policy: Authentication parameters; defaults to :class:`AuthPolicy`.
        """
        self._organizations = repositories.organizations
        self._api_keys = repositories.api_keys
        self._users = repositories.users
        self._sessions = repositories.sessions
        self._invitations = repositories.invitations
        self._policy = policy or AuthPolicy()

    # ------------------------------------------------------------------
    # API keys
    # ------------------------------------------------------------------

    def issue_key(self, org: Organization) -> ApiKeyCreated:
        """Issue a new API key for an organization.

        Args:
            org: The organization to issue a key for.

        Returns:
            The one-time reveal of the new key.

        Raises:
            AuthError: If no unused lookup prefix could be generated.
        """
        for _ in range(_KEY_ISSUE_ATTEMPTS):
            raw_key, prefix = generate_key()
            if self._api_keys.get_by_prefix(prefix) is None:
                record = self._api_keys.create(org.id, prefix, hash_key(raw_key))
                return ApiKeyCreated(id=record.id, org_id=org.id, raw_key=raw_key, prefix=prefix)
        raise AuthError("could not generate a unique API key prefix")

    def resolve_api_key(self, raw_key: str) -> OrgContext:
        """Authenticate a raw API key and resolve its org context.

        Args:
            raw_key: The key presented in the ``X-API-Key`` header.

        Returns:
            The authenticated context (``admin`` role).

        Raises:
            InvalidApiKeyError: If the key is missing, unknown, malformed or revoked.
        """
        if not raw_key:
            raise InvalidApiKeyError("missing API key")
        prefix = key_prefix(raw_key)
        record = self._api_keys.get_by_prefix(prefix)
        stored_hash = self._api_keys.get_hash(prefix) if record else None
        if record is None or stored_hash is None or not verify_key(raw_key, stored_hash):
            raise InvalidApiKeyError("invalid API key")
        if record.revoked_at is not None:
            raise InvalidApiKeyError("API key has been revoked")
        self._api_keys.touch_last_used(record.id)
        org = self._organizations.get(record.org_id)
        return OrgContext(
            org_id=org.id,
            org_name=org.name,
            principal=PrincipalType.API_KEY,
            role=Role.ADMIN,
            api_key_id=record.id,
        )

    def revoke_key(self, ctx: OrgContext) -> None:
        """Revoke the API key that authenticated ``ctx``.

        Args:
            ctx: The caller's context.

        Raises:
            ForbiddenError: If the caller did not authenticate with an API key.
            NotFoundError: If the key does not exist for this org.
        """
        if ctx.principal is not PrincipalType.API_KEY or ctx.api_key_id is None:
            raise ForbiddenError("only an API key can revoke itself; sign out instead")
        self._api_keys.revoke(ctx.org_id, ctx.api_key_id)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def login(self, email: str, password: str) -> SessionCreated:
        """Sign a user in with their email and password.

        Unknown emails and wrong passwords fail identically, and unknown
        emails still pay for one hash verification, so neither the message
        nor the timing reveals whether an account exists.

        Args:
            email: The account's email.
            password: The account's password.

        Returns:
            A new session.

        Raises:
            InvalidCredentialsError: If the email or password is wrong.
            AccountLockedError: If the account is locked after repeated failures.
        """
        now = self._policy.clock()
        credentials = self._users.get_credentials(normalize_email(email))
        if credentials is None:
            verify_against_dummy(password)
            raise InvalidCredentialsError(_INVALID_CREDENTIALS)
        user = credentials.user
        if credentials.locked_until is not None and credentials.locked_until > now:
            retry_after = math.ceil((credentials.locked_until - now).total_seconds())
            logger.warning("login_refused_locked", extra={"user_id": str(user.id)})
            raise AccountLockedError(
                "too many failed sign-in attempts; try again later", retry_after
            )
        if not verify_password(password, credentials.password_hash):
            self._users.record_login_failure(
                user.id, self._policy.max_login_attempts, now + self._policy.lockout
            )
            logger.info("login_failed", extra={"user_id": str(user.id)})
            raise InvalidCredentialsError(_INVALID_CREDENTIALS)

        self._users.record_login_success(user.id)
        if needs_rehash(credentials.password_hash):
            self._users.set_password(user.org_id, user.id, hash_password(password))
        self._sessions.delete_expired(now - _EXPIRED_SESSION_RETENTION)
        logger.info("login_succeeded", extra={"user_id": str(user.id)})
        return self._start_session(user)

    def resolve_session(self, token: str) -> OrgContext:
        """Authenticate a session token and resolve its org context.

        Args:
            token: The bearer token presented in ``Authorization``.

        Returns:
            The authenticated context, with the user's role.

        Raises:
            NotAuthenticatedError: If the token is unknown, expired or revoked.
        """
        if not token.startswith(SESSION_TOKEN_PREFIX):
            raise NotAuthenticatedError(_INVALID_SESSION)
        session = self._sessions.get_by_token_hash(token_digest(token))
        if (
            session is None
            or session.revoked_at is not None
            or session.expires_at <= self._policy.clock()
        ):
            raise NotAuthenticatedError(_INVALID_SESSION)
        try:
            user = self._users.get(session.org_id, session.user_id).user
            org = self._organizations.get(session.org_id)
        except NotFoundError as exc:  # the account was removed after sign-in
            raise NotAuthenticatedError(_INVALID_SESSION) from exc
        return OrgContext(
            org_id=org.id,
            org_name=org.name,
            principal=PrincipalType.USER,
            role=user.role,
            user_id=user.id,
            session_id=session.id,
            email=user.email,
        )

    def logout(self, ctx: OrgContext) -> None:
        """End the session that authenticated ``ctx``.

        Args:
            ctx: The caller's context.

        Raises:
            ForbiddenError: If the caller did not authenticate with a session.
        """
        session_id = self._require_user(ctx)[1]
        self._sessions.revoke(ctx.org_id, session_id)

    def change_password(self, ctx: OrgContext, current_password: str, new_password: str) -> None:
        """Change the signed-in user's password and end their other sessions.

        Args:
            ctx: The caller's context.
            current_password: The user's current password (re-authentication).
            new_password: The new password.

        Raises:
            ForbiddenError: If the caller is not a signed-in user, or the
                current password is wrong.
            PasswordPolicyError: If the new password fails the policy.
        """
        user_id, session_id = self._require_user(ctx)
        credentials = self._users.get(ctx.org_id, user_id)
        if not verify_password(current_password, credentials.password_hash):
            raise ForbiddenError("current password is incorrect")
        check_password_policy(
            new_password, credentials.user.email, self._policy.password_min_length
        )
        self._users.set_password(ctx.org_id, user_id, hash_password(new_password))
        revoked = self._sessions.revoke_all_for_user(ctx.org_id, user_id, session_id)
        logger.info(
            "password_changed", extra={"user_id": str(user_id), "sessions_revoked": revoked}
        )

    # ------------------------------------------------------------------
    # Invitations
    # ------------------------------------------------------------------

    def invite(self, ctx: OrgContext, request: InvitationCreate) -> InvitationCreated:
        """Invite someone to the caller's organization.

        Args:
            ctx: The caller's context; must have the ``admin`` role.
            request: Who to invite, and with which role.

        Returns:
            The one-time reveal of the invitation token and link.

        Raises:
            ForbiddenError: If the caller is not an admin.
            ConflictError: If the email already belongs to a member of this org.
        """
        if ctx.role is not Role.ADMIN:
            raise ForbiddenError("only organization admins can invite members")
        existing = self._users.get_credentials(request.email)
        if existing is not None and existing.user.org_id == ctx.org_id:
            raise ConflictError("this email already belongs to a member of your organization")
        return self._create_invitation(ctx.org_id, request.email, request.role, ctx.user_id)

    def invite_admin(self, org: Organization, email: str) -> InvitationCreated:
        """Invite an organization's first admin (operator bootstrap).

        Args:
            org: The organization.
            email: The admin's email.

        Returns:
            The one-time reveal of the invitation token and link.
        """
        return self._create_invitation(org.id, normalize_email(email), Role.ADMIN, None)

    def preview_invitation(self, token: str) -> tuple[Invitation, Organization]:
        """Look up a redeemable invitation without redeeming it.

        Args:
            token: The invitation token.

        Returns:
            The invitation and its organization.

        Raises:
            InvitationInvalidError: If the token is unknown, expired or used.
        """
        invitation = self._redeemable_invitation(token)
        return invitation, self._organizations.get(invitation.org_id)

    def accept_invitation(self, token: str, password: str) -> SessionCreated:
        """Redeem an invitation: create the account with a chosen password and sign in.

        Args:
            token: The invitation token.
            password: The password the invitee chose.

        Returns:
            A new session for the new user.

        Raises:
            InvitationInvalidError: If the token is unknown, expired or used.
            PasswordPolicyError: If the password fails the policy.
            ConflictError: If an account with the invitation's email exists.
        """
        invitation = self._redeemable_invitation(token)
        check_password_policy(password, invitation.email, self._policy.password_min_length)
        user = self._invitations.accept(
            invitation,
            User(org_id=invitation.org_id, email=invitation.email, role=invitation.role),
            hash_password(password),
        )
        logger.info(
            "invitation_accepted",
            extra={"user_id": str(user.id), "invitation_id": str(invitation.id)},
        )
        return self._start_session(user)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_session(self, user: User) -> SessionCreated:
        """Create and return a new session for ``user``."""
        token, digest = new_token(SESSION_TOKEN_PREFIX)
        session = self._sessions.create(
            UserSession(
                user_id=user.id,
                org_id=user.org_id,
                expires_at=self._policy.clock() + self._policy.session_ttl,
            ),
            digest,
        )
        org = self._organizations.get(user.org_id)
        return SessionCreated(
            token=token, expires_at=session.expires_at, user=user, org_name=org.name
        )

    def _create_invitation(
        self, org_id: uuid.UUID, email: str, role: Role, created_by: uuid.UUID | None
    ) -> InvitationCreated:
        """Store a new invitation and reveal its token once."""
        token, digest = new_token(INVITATION_TOKEN_PREFIX)
        invitation = self._invitations.create(
            Invitation(
                org_id=org_id,
                email=email,
                role=role,
                created_by=created_by,
                expires_at=self._policy.clock() + self._policy.invitation_ttl,
            ),
            digest,
        )
        logger.info(
            "invitation_created",
            extra={"invitation_id": str(invitation.id), "org_id": str(invitation.org_id)},
        )
        return InvitationCreated(
            id=invitation.id,
            email=invitation.email,
            role=invitation.role,
            expires_at=invitation.expires_at,
            token=token,
            accept_url=f"{self._policy.frontend_origin.rstrip('/')}/invite#token={token}",
        )

    def _redeemable_invitation(self, token: str) -> Invitation:
        """Return the invitation for ``token`` if it can still be redeemed."""
        if not token.startswith(INVITATION_TOKEN_PREFIX):
            raise InvitationInvalidError(_INVALID_INVITATION)
        invitation = self._invitations.get_by_token_hash(token_digest(token))
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.expires_at <= self._policy.clock()
        ):
            raise InvitationInvalidError(_INVALID_INVITATION)
        return invitation

    @staticmethod
    def _require_user(ctx: OrgContext) -> tuple[uuid.UUID, uuid.UUID]:
        """Return ``(user_id, session_id)``, or refuse a non-session caller."""
        if ctx.principal is not PrincipalType.USER or ctx.user_id is None or ctx.session_id is None:
            raise ForbiddenError("this action requires signing in as a user")
        return ctx.user_id, ctx.session_id
