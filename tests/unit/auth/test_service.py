import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from tests.fakes import FakeApiKeys, FakeUsers, fake_repositories

from dndlabs.auth.service import AuthPolicy, AuthService
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
    PasswordPolicyError,
)
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    InvitationCreate,
    Organization,
    OrgContext,
    PrincipalType,
    Role,
    SessionCreated,
)

PASSWORD = "correct horse battery"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def repos() -> Repositories:
    return fake_repositories()


@pytest.fixture
def service(repos: Repositories, clock: Clock) -> AuthService:
    policy = AuthPolicy(frontend_origin="https://app.example/", clock=clock)
    return AuthService(repos, policy)


@pytest.fixture
def org(repos: Repositories) -> Organization:
    return repos.organizations.create(Organization(name="Acme"))


def _admin_session(service: AuthService, org: Organization, email: str = "ada@acme.com") -> str:
    invitation = service.invite_admin(org, email)
    return service.accept_invitation(invitation.token, PASSWORD).token


# --- API keys ---------------------------------------------------------------


def test_issue_and_resolve_api_key(service: AuthService, org: Organization) -> None:
    created = service.issue_key(org)
    ctx = service.resolve_api_key(created.raw_key)
    assert (ctx.org_id, ctx.org_name) == (org.id, "Acme")
    assert ctx.principal is PrincipalType.API_KEY
    assert ctx.role is Role.ADMIN
    assert ctx.api_key_id == created.id


@pytest.mark.parametrize("raw", ["", "ddl_live_doesnotexist"])
def test_resolve_rejects_missing_or_unknown_key(service: AuthService, raw: str) -> None:
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(raw)


def test_resolve_rejects_wrong_secret_with_known_prefix(
    service: AuthService, org: Organization
) -> None:
    created = service.issue_key(org)
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(created.raw_key[:-4] + "xxxx")


def test_revoked_key_is_rejected(service: AuthService, org: Organization) -> None:
    created = service.issue_key(org)
    service.revoke_key(service.resolve_api_key(created.raw_key))
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(created.raw_key)


def test_revoke_key_requires_an_api_key_principal(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_session(_admin_session(service, org))
    with pytest.raises(ForbiddenError):
        service.revoke_key(ctx)


def test_revoke_key_of_another_org_is_not_found(service: AuthService, org: Organization) -> None:
    created = service.issue_key(org)
    ctx = service.resolve_api_key(created.raw_key).model_copy(update={"org_id": uuid.uuid4()})
    with pytest.raises(NotFoundError):
        service.revoke_key(ctx)


def test_issue_key_retries_on_prefix_collision(service: AuthService, org: Organization) -> None:
    first = service.issue_key(org)
    keys = iter([(first.raw_key, first.prefix), ("ddl_live_Zfresh", "ddl_live_Zfr")])
    with patch("dndlabs.auth.service.generate_key", lambda: next(keys)):
        second = service.issue_key(org)
    assert second.prefix == "ddl_live_Zfr"


def test_issue_key_gives_up_after_repeated_collisions(
    service: AuthService, org: Organization
) -> None:
    first = service.issue_key(org)
    with (
        patch("dndlabs.auth.service.generate_key", lambda: (first.raw_key, first.prefix)),
        pytest.raises(AuthError, match="unique"),
    ):
        service.issue_key(org)


# --- invitations --------------------------------------------------------------


def test_invitation_link_carries_the_token_in_the_fragment(
    service: AuthService, org: Organization
) -> None:
    invitation = service.invite_admin(org, "Ada@Acme.com")
    assert invitation.email == "ada@acme.com"
    assert invitation.role is Role.ADMIN
    assert invitation.token.startswith("ddl_inv_")
    assert invitation.accept_url == f"https://app.example/invite#token={invitation.token}"


def test_accepting_an_invitation_creates_the_user_and_signs_in(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    invitation = service.invite_admin(org, "ada@acme.com")
    preview, preview_org = service.preview_invitation(invitation.token)
    assert (preview.email, preview_org.name) == ("ada@acme.com", "Acme")

    session = service.accept_invitation(invitation.token, PASSWORD)

    assert session.token.startswith("ddl_sess_")
    assert session.user.email == "ada@acme.com"
    assert session.user.role is Role.ADMIN
    assert session.org_name == "Acme"
    assert session.expires_at == clock.now + timedelta(hours=12)
    ctx = service.resolve_session(session.token)
    assert (ctx.principal, ctx.user_id, ctx.email) == (
        PrincipalType.USER,
        session.user.id,
        "ada@acme.com",
    )


def test_invitation_is_single_use(service: AuthService, org: Organization) -> None:
    invitation = service.invite_admin(org, "ada@acme.com")
    service.accept_invitation(invitation.token, PASSWORD)
    with pytest.raises(InvitationInvalidError):
        service.accept_invitation(invitation.token, PASSWORD)
    with pytest.raises(InvitationInvalidError):
        service.preview_invitation(invitation.token)


def test_expired_invitation_is_rejected(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    invitation = service.invite_admin(org, "ada@acme.com")
    clock.advance(timedelta(hours=72))
    with pytest.raises(InvitationInvalidError):
        service.accept_invitation(invitation.token, PASSWORD)


@pytest.mark.parametrize("token", ["", "ddl_inv_unknown", "ddl_sess_wrongtype"])
def test_unknown_invitation_token_is_rejected(service: AuthService, token: str) -> None:
    with pytest.raises(InvitationInvalidError):
        service.accept_invitation(token, PASSWORD)


def test_weak_password_leaves_the_invitation_usable(
    service: AuthService, org: Organization
) -> None:
    invitation = service.invite_admin(org, "ada@acme.com")
    with pytest.raises(PasswordPolicyError):
        service.accept_invitation(invitation.token, "short")
    assert service.accept_invitation(invitation.token, PASSWORD).user.email == "ada@acme.com"


def test_accepting_for_an_email_that_already_has_an_account_conflicts(
    service: AuthService, repos: Repositories
) -> None:
    acme = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    _admin_session(service, acme, "ada@acme.com")
    invitation = service.invite_admin(other, "ada@acme.com")
    with pytest.raises(ConflictError):
        service.accept_invitation(invitation.token, PASSWORD)


def test_admin_can_invite_member_who_cannot_invite(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org))
    invitation = service.invite(admin, InvitationCreate(email="bob@acme.com"))
    assert invitation.role is Role.MEMBER

    member = service.resolve_session(service.accept_invitation(invitation.token, PASSWORD).token)
    assert member.role is Role.MEMBER
    with pytest.raises(ForbiddenError):
        service.invite(member, InvitationCreate(email="eve@acme.com"))


def test_api_key_can_invite(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_api_key(service.issue_key(org).raw_key)
    invitation = service.invite(ctx, InvitationCreate(email="bob@acme.com", role=Role.ADMIN))
    assert invitation.role is Role.ADMIN


def test_inviting_an_existing_member_conflicts(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org))
    with pytest.raises(ConflictError):
        service.invite(admin, InvitationCreate(email="ADA@acme.com"))


# --- sign-in ------------------------------------------------------------------


def test_login_is_case_insensitive_on_email(service: AuthService, org: Organization) -> None:
    _admin_session(service, org)
    session = service.login("  ADA@Acme.com ", PASSWORD)
    assert service.resolve_session(session.token).email == "ada@acme.com"


def test_wrong_password_and_unknown_email_fail_identically(
    service: AuthService, org: Organization
) -> None:
    _admin_session(service, org)
    with pytest.raises(InvalidCredentialsError) as wrong:
        service.login("ada@acme.com", "not the password")
    with (
        patch("dndlabs.auth.service.verify_against_dummy") as dummy,
        pytest.raises(InvalidCredentialsError) as unknown,
    ):
        service.login("nobody@acme.com", PASSWORD)
    assert str(wrong.value) == str(unknown.value) == "invalid email or password"
    dummy.assert_called_once_with(PASSWORD)


def test_repeated_failures_lock_the_account_until_the_lockout_ends(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    _admin_session(service, org)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            service.login("ada@acme.com", "not the password")

    with pytest.raises(AccountLockedError) as locked:
        service.login("ada@acme.com", PASSWORD)  # even the right password
    assert locked.value.retry_after_seconds == 15 * 60

    clock.advance(timedelta(minutes=15))
    assert isinstance(service.login("ada@acme.com", PASSWORD), SessionCreated)


def test_successful_login_resets_the_failure_count(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    _admin_session(service, org)
    for _ in range(4):
        with pytest.raises(InvalidCredentialsError):
            service.login("ada@acme.com", "not the password")
    service.login("ada@acme.com", PASSWORD)
    creds = repos.users.get_credentials("ada@acme.com")
    assert creds is not None and creds.failed_login_count == 0


def test_login_upgrades_an_outdated_hash(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    _admin_session(service, org)
    users: FakeUsers = repos.users  # type: ignore[assignment]
    before = users.get_credentials("ada@acme.com")
    assert before is not None
    with patch("dndlabs.auth.service.needs_rehash", return_value=True):
        service.login("ada@acme.com", PASSWORD)
    after = users.get_credentials("ada@acme.com")
    assert after is not None and after.password_hash != before.password_hash
    service.login("ada@acme.com", PASSWORD)  # the new hash verifies


def test_login_purges_long_expired_sessions(
    service: AuthService, org: Organization, repos: Repositories, clock: Clock
) -> None:
    old = _admin_session(service, org)
    clock.advance(timedelta(days=31))
    service.login("ada@acme.com", PASSWORD)
    assert all(s.expires_at > clock.now - timedelta(days=30) for s in repos.sessions.items.values())  # type: ignore[attr-defined]
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(old)


# --- sessions -----------------------------------------------------------------


@pytest.mark.parametrize("token", ["", "ddl_live_notasession", "ddl_sess_unknown"])
def test_unknown_session_token_is_rejected(service: AuthService, token: str) -> None:
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token)


def test_session_of_a_removed_user_is_rejected(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    token = _admin_session(service, org)
    repos.users.items.clear()  # type: ignore[attr-defined]
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token)


def test_session_expires(service: AuthService, org: Organization, clock: Clock) -> None:
    token = _admin_session(service, org)
    clock.advance(timedelta(hours=12))
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token)


def test_logout_revokes_only_the_calling_session(service: AuthService, org: Organization) -> None:
    first = _admin_session(service, org)
    second = service.login("ada@acme.com", PASSWORD).token
    service.logout(service.resolve_session(first))
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(first)
    assert service.resolve_session(second).email == "ada@acme.com"


def test_logout_requires_a_session(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_api_key(service.issue_key(org).raw_key)
    with pytest.raises(ForbiddenError):
        service.logout(ctx)


def test_change_password_ends_other_sessions(service: AuthService, org: Organization) -> None:
    current = _admin_session(service, org)
    other = service.login("ada@acme.com", PASSWORD).token
    new_password = "a different long passphrase"

    service.change_password(service.resolve_session(current), PASSWORD, new_password)

    assert service.resolve_session(current).email == "ada@acme.com"
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(other)
    with pytest.raises(InvalidCredentialsError):
        service.login("ada@acme.com", PASSWORD)
    service.login("ada@acme.com", new_password)


def test_change_password_checks_the_current_password_and_policy(
    service: AuthService, org: Organization
) -> None:
    ctx = service.resolve_session(_admin_session(service, org))
    with pytest.raises(ForbiddenError, match="current password"):
        service.change_password(ctx, "not the password", "a different long passphrase")
    with pytest.raises(PasswordPolicyError):
        service.change_password(ctx, PASSWORD, "ada@acme.com")


def test_change_password_requires_a_session(service: AuthService, org: Organization) -> None:
    ctx: OrgContext = service.resolve_api_key(service.issue_key(org).raw_key)
    with pytest.raises(ForbiddenError):
        service.change_password(ctx, PASSWORD, "a different long passphrase")


def test_default_policy_is_used_when_none_is_given(repos: Repositories) -> None:
    service = AuthService(repos)
    org = repos.organizations.create(Organization(name="Acme"))
    assert service.invite_admin(org, "a@b.co").accept_url.startswith("http://localhost:5173/")
    assert isinstance(repos.api_keys, FakeApiKeys)
