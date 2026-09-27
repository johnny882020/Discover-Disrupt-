"""Authentication: API keys, user sign-in sessions and invitations.

Two kinds of principal authenticate a request, both resolved to an
:class:`~dndlabs.core.schemas.OrgContext`:

- **API keys** (``X-API-Key``) for programmatic access. Argon2-hashed,
  looked up by a non-secret prefix, and acting with the ``admin`` role.
- **User sessions** (``Authorization: Bearer ddl_sess_…``) for people using
  the web app. A user joins an organization by redeeming a single-use
  invitation, choosing their own password; signing in exchanges the email
  and password for an opaque, expiring, revocable session token.

Brute force is limited per client IP and per email in database-backed
fixed windows (:mod:`dndlabs.auth.ratelimit`). See docs/architecture.md#auth.
"""

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
from dndlabs.auth.ratelimit import (
    RateLimiter,
    Window,
    auth_failure_bucket,
    signin_email_bucket,
    signin_email_ip_bucket,
    signin_ip_bucket,
)
from dndlabs.auth.tokens import (
    INVITATION_TOKEN_PREFIX,
    SESSION_TOKEN_PREFIX,
    new_token,
    token_digest,
)
from dndlabs.core.exceptions import (
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
    InvitationPurpose,
    Organization,
    OrgContext,
    PasswordResetCreated,
    PrincipalType,
    Role,
    SessionCreated,
    User,
    UserSession,
    normalize_email,
    utcnow,
)

logger = get_logger(__name__)

#: How many times ``issue_key`` retries after a prefix collision (with 72
#: random bits, even one is vanishingly unlikely).
_KEY_ISSUE_ATTEMPTS = 5
#: Expired sessions are kept this long (for audit) before housekeeping deletes them.
_EXPIRED_SESSION_RETENTION = timedelta(days=30)

# One fixed message per failure family, so the text never says which check
# failed (unknown email vs. wrong password, unknown vs. expired token).
_INVALID_CREDENTIALS = "invalid email or password"
_INVALID_SESSION = "invalid or expired session"
_INVALID_INVITATION = "invitation is invalid, expired or already used"


@dataclass(frozen=True)
class AuthPolicy:
    """Tunable parameters of user authentication.

    Attributes:
        session_ttl: Absolute lifetime of a sign-in session.
        invitation_ttl: How long an invitation can be redeemed.
        password_reset_ttl: How long a password-reset link can be redeemed.
        rate_limit_window: Length of a brute-force limit's fixed window.
        signin_limit_per_ip: Sign-in attempts per window from one client IP.
        signin_limit_per_email_and_ip: Sign-in attempts per window for one
            email from one client IP.
        signin_limit_per_email: Sign-in attempts per window for one email
            from all IPs together.
        auth_failure_limit_per_ip: Failed API-key or session-token
            authentications per window from one client IP.
        password_min_length: Minimum password length.
        frontend_origin: Web app origin; invitation links point here.
        clock: Current-time source (injectable for tests).
    """

    session_ttl: timedelta = timedelta(hours=12)
    invitation_ttl: timedelta = timedelta(hours=72)
    password_reset_ttl: timedelta = timedelta(hours=24)
    rate_limit_window: timedelta = timedelta(minutes=15)
    signin_limit_per_ip: int = 20
    signin_limit_per_email_and_ip: int = 5
    signin_limit_per_email: int = 50
    auth_failure_limit_per_ip: int = 50
    password_min_length: int = 12
    frontend_origin: str = "http://localhost:5173"
    clock: Callable[[], datetime] = field(default=utcnow)


class AuthService:
    """Issues and verifies credentials against the auth repositories."""

    def __init__(self, repositories: Repositories, policy: AuthPolicy | None = None) -> None:
        """Create the service.

        Args:
            repositories: Repository bundle (organizations, API keys, users,
                sessions, invitations and rate limits are used).
            policy: Authentication parameters; defaults to :class:`AuthPolicy`.
        """
        self._organizations = repositories.organizations
        self._api_keys = repositories.api_keys
        self._users = repositories.users
        self._sessions = repositories.sessions
        self._invitations = repositories.invitations
        self._policy = policy or AuthPolicy()
        self._limiter = RateLimiter(
            repositories.rate_limits, self._policy.rate_limit_window, self._policy.clock
        )

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
            ConflictError: If every attempt drew a prefix already in use
                (409, safe to retry; never a 500).
        """
        for _ in range(_KEY_ISSUE_ATTEMPTS):
            raw_key, prefix = generate_key()
            # No lookup first: the unique index decides, so a prefix taken
            # by a concurrent issue between a check and the insert is caught
            # the same way as any other collision.
            try:
                record = self._api_keys.create(org.id, prefix, hash_key(raw_key))
            except ConflictError:
                logger.warning("api_key_prefix_collision", extra={"org_id": str(org.id)})
                continue
            return ApiKeyCreated(id=record.id, org_id=org.id, raw_key=raw_key, prefix=prefix)
        raise ConflictError("could not issue an API key; try again")

    def resolve_api_key(self, raw_key: str, client_ip: str) -> OrgContext:
        """Authenticate a raw API key and resolve its org context.

        Failed attempts are counted per client IP. Once an IP reaches
        ``auth_failure_limit_per_ip`` in a window, a key with a known prefix
        is refused before its Argon2 hash is verified, so failures cannot
        force unbounded 64 MiB hashes. That refuses a valid key sent from
        the same IP too, until the window ends — telling it apart would take
        the very hash the limit exists to bound. A valid key never counts
        against the limit.

        Args:
            raw_key: The key presented in the ``X-API-Key`` header.
            client_ip: The client's IP address.

        Returns:
            The authenticated context (``admin`` role).

        Raises:
            InvalidApiKeyError: If the key is missing, unknown, malformed or revoked.
            RateLimitedError: If the client IP has too many recent failures.
        """
        if not raw_key:
            raise InvalidApiKeyError("missing API key")
        window = self._limiter.window()
        failures = auth_failure_bucket(client_ip)
        prefix = key_prefix(raw_key)
        record = self._api_keys.get_by_prefix(prefix)
        stored_hash = self._api_keys.get_hash(prefix) if record else None
        if record is None or stored_hash is None:
            # No hash is verified for an unknown prefix, so there is nothing
            # to protect before counting the failure.
            self._authentication_failed(failures, window)
            raise InvalidApiKeyError("invalid API key")
        # A read, not a hit: a valid key must not cost a write or count. The
        # check-then-count race only lets requests already in flight through,
        # so Argon2 work stays bounded by the limit plus the server's
        # concurrency per window.
        self._limiter.check(failures, self._policy.auth_failure_limit_per_ip, window)
        # Revocation is checked only after the hash matches, so "revoked" is
        # only ever told to a holder of the real key (and is not counted).
        if not verify_key(raw_key, stored_hash):
            self._authentication_failed(failures, window)
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

    def login(self, email: str, password: str, client_ip: str) -> SessionCreated:
        """Sign a user in with their email and password.

        Nothing reveals whether an account exists: unknown emails and wrong
        passwords fail with the same message, unknown emails still pay for
        one hash verification (same timing), and the limits below count
        attempts per email whether or not it has an account, so both reach
        ``429`` after the same number of attempts.

        Every attempt is counted, before any lookup or hash, in three
        buckets: the client IP (credential stuffing across many emails),
        the email from this IP, and the email from all IPs (guessing spread
        over many IPs). A successful sign-in is taken back out, so only
        failures accumulate.

        Args:
            email: The account's email.
            password: The account's password.
            client_ip: The client's IP address.

        Returns:
            A new session.

        Raises:
            InvalidCredentialsError: If the email or password is wrong.
            RateLimitedError: If a sign-in limit is reached; even the right
                password is refused, and nothing is verified.
        """
        email = normalize_email(email)
        window = self._limiter.window()
        # Housekeeping piggybacks on sign-in; there is no separate sweeper.
        self._limiter.purge_expired(window)
        ip_bucket = signin_ip_bucket(client_ip)
        email_bucket = signin_email_bucket(email)
        # Lockout denial of service: someone who knows an email could keep
        # it refused by failing on purpose. The per-(email, IP) bucket is the
        # tight one (5 attempts by default), and it only refuses that IP, so
        # one attacker cannot lock the owner out. The
        # per-email bucket, checked last so attempts refused per IP never
        # reach it, is looser: it bounds guessing distributed over many IPs,
        # at the price that an attacker with enough IPs (limit / per-IP
        # limit, 10 by default) can still exhaust it for the window.
        # Counting before verifying bounds Argon2 work per window, even
        # for requests sent concurrently.
        self._limiter.hit(ip_bucket, self._policy.signin_limit_per_ip, window)
        self._limiter.hit(
            signin_email_ip_bucket(email, client_ip),
            self._policy.signin_limit_per_email_and_ip,
            window,
        )
        self._limiter.hit(email_bucket, self._policy.signin_limit_per_email, window)

        credentials = self._users.get_credentials(email)
        if credentials is None:
            verify_against_dummy(password)
            raise InvalidCredentialsError(_INVALID_CREDENTIALS)
        user = credentials.user
        if not verify_password(password, credentials.password_hash):
            logger.info("login_failed", extra={"user_id": str(user.id)})
            raise InvalidCredentialsError(_INVALID_CREDENTIALS)

        # Only the password's holder gets here, so this reveals nothing. The
        # IP's attempt is refunded (a shared office IP is not limited by its
        # successful sign-ins), and the email's counters are cleared, so the
        # owner's own earlier typos do not linger into their next sign-in.
        self._limiter.refund(ip_bucket, window)
        self._limiter.clear(email_bucket)
        # The plaintext is only available here, at a successful sign-in.
        if needs_rehash(credentials.password_hash):
            self._users.set_password(user.org_id, user.id, hash_password(password))
        self._sessions.delete_expired(window.now - _EXPIRED_SESSION_RETENTION)
        logger.info("login_succeeded", extra={"user_id": str(user.id)})
        return self._start_session(user)

    def resolve_session(self, token: str, client_ip: str) -> OrgContext:
        """Authenticate a session token and resolve its org context.

        Failures are counted per client IP, like API-key failures. A valid
        token is never refused: checking one costs a SHA-256 and an indexed
        lookup, not an Argon2 hash, so there is nothing to protect by
        refusing it early.

        Args:
            token: The bearer token presented in ``Authorization``.
            client_ip: The client's IP address.

        Returns:
            The authenticated context, with the user's role.

        Raises:
            NotAuthenticatedError: If the token is unknown, expired or revoked.
            RateLimitedError: If the client IP has too many recent failures.
        """
        window = self._limiter.window()
        failures = auth_failure_bucket(client_ip)
        if not token.startswith(SESSION_TOKEN_PREFIX):
            self._authentication_failed(failures, window)
            raise NotAuthenticatedError(_INVALID_SESSION)
        # Looked up by digest (see auth.tokens): the raw token is never stored
        # or compared, so equality-match timing reveals nothing usable.
        session = self._sessions.get_by_token_hash(token_digest(token))
        if session is None or session.revoked_at is not None or session.expires_at <= window.now:
            self._authentication_failed(failures, window)
            raise NotAuthenticatedError(_INVALID_SESSION)
        try:
            user = self._users.get(session.org_id, session.user_id).user
            org = self._organizations.get(session.org_id)
        except NotFoundError as exc:  # the account was removed after sign-in
            self._authentication_failed(failures, window)
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
        # Ends every other session (the calling one is kept), so a stolen
        # session dies once its owner changes the password.
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
        self._require_admin(ctx)
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
        invitation = self._redeemable_invitation(token, InvitationPurpose.JOIN)
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
        invitation = self._redeemable_invitation(token, InvitationPurpose.JOIN)
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

    def list_pending_invitations(self, ctx: OrgContext) -> list[Invitation]:
        """List the organization's invitations that can still be accepted.

        Args:
            ctx: The caller's context; must have the ``admin`` role.

        Returns:
            Pending invitations, newest first.

        Raises:
            ForbiddenError: If the caller is not an admin.
        """
        self._require_admin(ctx)
        return self._invitations.list_pending(
            ctx.org_id, InvitationPurpose.JOIN, self._policy.clock()
        )

    def revoke_invitation(self, ctx: OrgContext, invitation_id: uuid.UUID) -> None:
        """Revoke a pending invitation so its link stops working.

        Args:
            ctx: The caller's context; must have the ``admin`` role.
            invitation_id: The invitation to revoke.

        Raises:
            ForbiddenError: If the caller is not an admin.
            NotFoundError: If no pending invitation has this id in the org.
        """
        self._require_admin(ctx)
        self._invitations.revoke(ctx.org_id, invitation_id)
        logger.info("invitation_revoked", extra={"invitation_id": str(invitation_id)})

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------

    def list_members(self, ctx: OrgContext) -> list[User]:
        """List the organization's user accounts.

        Args:
            ctx: The caller's context; must have the ``admin`` role.

        Returns:
            The users, oldest first.

        Raises:
            ForbiddenError: If the caller is not an admin.
        """
        self._require_admin(ctx)
        return self._users.list_members(ctx.org_id)

    def set_member_role(self, ctx: OrgContext, user_id: uuid.UUID, role: Role) -> User:
        """Change a member's role.

        Args:
            ctx: The caller's context; must have the ``admin`` role.
            user_id: The member.
            role: The new role.

        Returns:
            The updated member.

        Raises:
            ForbiddenError: If the caller is not an admin.
            NotFoundError: If the user is not a member of the org.
            ConflictError: If this would leave the org without an admin user.
        """
        self._require_admin(ctx)
        member = self._users.get(ctx.org_id, user_id).user
        if member.role is Role.ADMIN and role is not Role.ADMIN:
            self._require_another_admin(ctx.org_id, user_id)
        updated = self._users.set_role(ctx.org_id, user_id, role)
        logger.info("member_role_changed", extra={"user_id": str(user_id), "role": role.value})
        return updated

    def remove_member(self, ctx: OrgContext, user_id: uuid.UUID) -> None:
        """Remove a member: their account and sessions are deleted immediately.

        Args:
            ctx: The caller's context; must have the ``admin`` role.
            user_id: The member to remove.

        Raises:
            ForbiddenError: If the caller is not an admin, or removes themselves.
            NotFoundError: If the user is not a member of the org.
            ConflictError: If this would leave the org without an admin user.
        """
        self._require_admin(ctx)
        if ctx.user_id == user_id:
            raise ForbiddenError("you cannot remove yourself; ask another admin")
        member = self._users.get(ctx.org_id, user_id).user
        if member.role is Role.ADMIN:
            self._require_another_admin(ctx.org_id, user_id)
        self._users.delete(ctx.org_id, user_id)
        logger.info("member_removed", extra={"user_id": str(user_id)})

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    def issue_password_reset(self, ctx: OrgContext, user_id: uuid.UUID) -> PasswordResetCreated:
        """Issue a single-use password-reset link for a member.

        Any earlier unused reset link for the same member stops working.

        Args:
            ctx: The caller's context; must have the ``admin`` role.
            user_id: The member whose password is reset.

        Returns:
            The one-time reveal of the reset token and link.

        Raises:
            ForbiddenError: If the caller is not an admin.
            NotFoundError: If the user is not a member of the org.
        """
        self._require_admin(ctx)
        member = self._users.get(ctx.org_id, user_id).user
        return self._create_password_reset(member, ctx.user_id)

    def issue_password_reset_for_email(self, org: Organization, email: str) -> PasswordResetCreated:
        """Issue a password-reset link for an organization's user (operator bootstrap).

        Args:
            org: The organization.
            email: The user's email.

        Returns:
            The one-time reveal of the reset token and link.

        Raises:
            NotFoundError: If no user with this email belongs to the org.
        """
        credentials = self._users.get_credentials(normalize_email(email))
        if credentials is None or credentials.user.org_id != org.id:
            raise NotFoundError(f"no user {normalize_email(email)} in organization {org.id}")
        return self._create_password_reset(credentials.user, None)

    def preview_password_reset(self, token: str) -> tuple[Invitation, Organization]:
        """Look up a redeemable password-reset token without redeeming it.

        Args:
            token: The reset token.

        Returns:
            The token's metadata and its organization.

        Raises:
            InvitationInvalidError: If the token is unknown, expired, used or revoked.
        """
        reset = self._redeemable_invitation(token, InvitationPurpose.PASSWORD_RESET)
        return reset, self._organizations.get(reset.org_id)

    def reset_password(self, token: str, password: str) -> SessionCreated:
        """Redeem a reset token: set the new password, end all sessions, sign in.

        Args:
            token: The reset token.
            password: The new password.

        Returns:
            A new session for the user.

        Raises:
            InvitationInvalidError: If the token is unknown, expired, used or
                revoked, or its account no longer exists.
            PasswordPolicyError: If the password fails the policy.
        """
        reset = self._redeemable_invitation(token, InvitationPurpose.PASSWORD_RESET)
        check_password_policy(password, reset.email, self._policy.password_min_length)
        user = self._invitations.redeem_password_reset(reset, hash_password(password))
        # Lifts the email's sign-in limits (every IP), so a user refused
        # after failed attempts can sign in with the new password at once.
        self._limiter.clear(signin_email_bucket(user.email))
        logger.info("password_reset", extra={"user_id": str(user.id)})
        return self._start_session(user)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _authentication_failed(self, bucket: str, window: Window) -> None:
        """Count a failed API-key or session authentication from a client IP.

        Raises:
            RateLimitedError: If this failure exceeds the per-IP limit (the
                caller raises its 401 otherwise).
        """
        self._limiter.hit(bucket, self._policy.auth_failure_limit_per_ip, window)

    @staticmethod
    def _require_admin(ctx: OrgContext) -> None:
        """Refuse a caller without the ``admin`` role."""
        if ctx.role is not Role.ADMIN:
            raise ForbiddenError("only organization admins can manage members")

    def _require_another_admin(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Refuse a change that would leave the org without an admin user."""
        admins = [
            u for u in self._users.list_members(org_id) if u.role is Role.ADMIN and u.id != user_id
        ]
        if not admins:
            raise ConflictError("an organization must keep at least one admin")

    def _create_password_reset(
        self, user: User, created_by: uuid.UUID | None
    ) -> PasswordResetCreated:
        """Store a reset token for ``user`` (superseding older ones) and reveal it once."""
        now = self._policy.clock()
        for pending in self._invitations.list_pending(
            user.org_id, InvitationPurpose.PASSWORD_RESET, now
        ):
            if pending.email == user.email:
                self._invitations.revoke(user.org_id, pending.id)
        token, digest = new_token(INVITATION_TOKEN_PREFIX)
        reset = self._invitations.create(
            Invitation(
                org_id=user.org_id,
                email=user.email,
                role=user.role,
                purpose=InvitationPurpose.PASSWORD_RESET,
                created_by=created_by,
                expires_at=now + self._policy.password_reset_ttl,
            ),
            digest,
        )
        logger.info(
            "password_reset_issued", extra={"user_id": str(user.id), "token_id": str(reset.id)}
        )
        return PasswordResetCreated(
            email=reset.email,
            expires_at=reset.expires_at,
            token=token,
            # Token in the URL fragment: browsers never send it to a server,
            # so it stays out of access logs and Referer headers.
            reset_url=f"{self._policy.frontend_origin.rstrip('/')}/reset#token={token}",
        )

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
            # Fragment, not query: see _create_password_reset.
            accept_url=f"{self._policy.frontend_origin.rstrip('/')}/invite#token={token}",
        )

    def _redeemable_invitation(self, token: str, purpose: InvitationPurpose) -> Invitation:
        """Return the token's invitation if it has ``purpose`` and can still be redeemed."""
        if not token.startswith(INVITATION_TOKEN_PREFIX):
            raise InvitationInvalidError(_INVALID_INVITATION)
        invitation = self._invitations.get_by_token_hash(token_digest(token))
        # Purpose must match, so a join token cannot reset a password and a
        # reset token cannot create an account.
        if (
            invitation is None
            or invitation.purpose is not purpose
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
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
