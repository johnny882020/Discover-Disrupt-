import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from tests.fakes import FakeApiKeys, FakeUsers, fake_repositories

from dndlabs.auth.service import AuthPolicy, AuthService
from dndlabs.core.exceptions import (
    ConflictError,
    ForbiddenError,
    InvalidApiKeyError,
    InvalidCredentialsError,
    InvitationInvalidError,
    NotAuthenticatedError,
    NotFoundError,
    PasswordPolicyError,
    RateLimitedError,
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
IP = "203.0.113.7"


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
    ctx = service.resolve_api_key(created.raw_key, IP)
    assert (ctx.org_id, ctx.org_name) == (org.id, "Acme")
    assert ctx.principal is PrincipalType.API_KEY
    assert ctx.role is Role.ADMIN
    assert ctx.api_key_id == created.id


@pytest.mark.parametrize("raw", ["", "ddl_live_doesnotexist"])
def test_resolve_rejects_missing_or_unknown_key(service: AuthService, raw: str) -> None:
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(raw, IP)


def test_resolve_rejects_wrong_secret_with_known_prefix(
    service: AuthService, org: Organization
) -> None:
    created = service.issue_key(org)
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(created.raw_key[:-4] + "xxxx", IP)


def test_revoked_key_is_rejected(service: AuthService, org: Organization) -> None:
    created = service.issue_key(org)
    service.revoke_key(service.resolve_api_key(created.raw_key, IP))
    with pytest.raises(InvalidApiKeyError):
        service.resolve_api_key(created.raw_key, IP)


def test_revoke_key_requires_an_api_key_principal(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_session(_admin_session(service, org), IP)
    with pytest.raises(ForbiddenError):
        service.revoke_key(ctx)


def test_revoke_key_of_another_org_is_not_found(service: AuthService, org: Organization) -> None:
    created = service.issue_key(org)
    ctx = service.resolve_api_key(created.raw_key, IP).model_copy(update={"org_id": uuid.uuid4()})
    with pytest.raises(NotFoundError):
        service.revoke_key(ctx)


def test_issue_key_retries_on_prefix_collision(service: AuthService, org: Organization) -> None:
    first = service.issue_key(org)
    keys = iter([(first.raw_key, first.prefix), ("ddl_live_Zfresh", "ddl_live_Zfr")])
    with patch("dndlabs.auth.service.generate_key", lambda: next(keys)):
        second = service.issue_key(org)
    assert second.prefix == "ddl_live_Zfr"


def test_a_key_issued_with_the_old_short_prefix_still_resolves(
    service: AuthService, repos: Repositories, org: Organization
) -> None:
    from dndlabs.auth.models import hash_key

    legacy = "ddl_live_" + "k" * 43
    repos.api_keys.create(org.id, "ddl_live_kkk", hash_key(legacy))
    assert service.resolve_api_key(legacy, IP).org_id == org.id


def test_issue_key_gives_up_after_repeated_collisions(
    service: AuthService, org: Organization
) -> None:
    first = service.issue_key(org)
    with (
        patch("dndlabs.auth.service.generate_key", lambda: (first.raw_key, first.prefix)),
        pytest.raises(ConflictError, match="try again"),
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
    ctx = service.resolve_session(session.token, IP)
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
    admin = service.resolve_session(_admin_session(service, org), IP)
    invitation = service.invite(admin, InvitationCreate(email="bob@acme.com"))
    assert invitation.role is Role.MEMBER

    member = service.resolve_session(
        service.accept_invitation(invitation.token, PASSWORD).token, IP
    )
    assert member.role is Role.MEMBER
    with pytest.raises(ForbiddenError):
        service.invite(member, InvitationCreate(email="eve@acme.com"))


def test_api_key_can_invite(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_api_key(service.issue_key(org).raw_key, IP)
    invitation = service.invite(ctx, InvitationCreate(email="bob@acme.com", role=Role.ADMIN))
    assert invitation.role is Role.ADMIN


def test_inviting_an_existing_member_conflicts(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    with pytest.raises(ConflictError):
        service.invite(admin, InvitationCreate(email="ADA@acme.com"))


# --- sign-in ------------------------------------------------------------------


def test_login_is_case_insensitive_on_email(service: AuthService, org: Organization) -> None:
    _admin_session(service, org)
    session = service.login("  ADA@Acme.com ", PASSWORD, IP)
    assert service.resolve_session(session.token, IP).email == "ada@acme.com"


def test_wrong_password_and_unknown_email_fail_identically(
    service: AuthService, org: Organization
) -> None:
    _admin_session(service, org)
    with pytest.raises(InvalidCredentialsError) as wrong:
        service.login("ada@acme.com", "not the password", IP)
    with (
        patch("dndlabs.auth.service.verify_against_dummy") as dummy,
        pytest.raises(InvalidCredentialsError) as unknown,
    ):
        service.login("nobody@acme.com", PASSWORD, IP)
    assert str(wrong.value) == str(unknown.value) == "invalid email or password"
    dummy.assert_called_once_with(PASSWORD)


def _fail_login(service: AuthService, email: str, ip: str = IP) -> None:
    with pytest.raises(InvalidCredentialsError):
        service.login(email, "not the password", ip)


def test_repeated_failures_refuse_the_email_from_that_ip_until_the_window_ends(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    _admin_session(service, org)
    for _ in range(5):
        _fail_login(service, "ada@acme.com")

    with (
        patch("dndlabs.auth.service.verify_password") as verify,
        pytest.raises(RateLimitedError) as limited,
    ):
        service.login("ada@acme.com", PASSWORD, IP)  # even the right password
    verify.assert_not_called()  # refused before any hash work
    assert limited.value.retry_after_seconds == 15 * 60  # the clock sits on a window start

    # Another IP is not refused: failing on purpose cannot lock the owner out.
    assert isinstance(service.login("ada@acme.com", PASSWORD, "198.51.100.9"), SessionCreated)

    clock.advance(timedelta(minutes=15))
    assert isinstance(service.login("ada@acme.com", PASSWORD, IP), SessionCreated)


def test_retry_after_counts_down_to_the_end_of_the_window(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    clock.advance(timedelta(minutes=10, seconds=30))
    for _ in range(5):
        _fail_login(service, "nobody@acme.com")
    with pytest.raises(RateLimitedError) as limited:
        service.login("nobody@acme.com", PASSWORD, IP)
    assert limited.value.retry_after_seconds == 4 * 60 + 30


def test_unknown_and_known_emails_are_indistinguishable(
    service: AuthService, org: Organization
) -> None:
    _admin_session(service, org)

    def attempts(email: str) -> list[str]:
        outcomes = []
        for _ in range(7):
            with (
                patch("dndlabs.auth.service.verify_password", return_value=False) as real,
                patch("dndlabs.auth.service.verify_against_dummy") as dummy,
            ):
                try:
                    service.login(email, "not the password", IP)
                except (InvalidCredentialsError, RateLimitedError) as exc:
                    outcomes.append(f"{type(exc).__name__}: {exc}")
            # Exactly one hash verification per attempt that is not refused
            # (dummy for an unknown email), none once refused: same timing.
            outcomes[-1] += f" hashes={real.call_count + dummy.call_count}"
        return outcomes

    known, unknown = attempts("ada@acme.com"), attempts("nobody@acme.com")
    assert known == unknown
    assert known[:5] == ["InvalidCredentialsError: invalid email or password hashes=1"] * 5
    assert known[5:] == ["RateLimitedError: signin-email-ip limit reached hashes=0"] * 2


def test_the_client_ip_is_limited_across_emails(repos: Repositories, clock: Clock) -> None:
    service = AuthService(repos, AuthPolicy(clock=clock, signin_limit_per_ip=3))
    with patch("dndlabs.auth.service.verify_against_dummy"):
        for n in range(3):
            _fail_login(service, f"user{n}@acme.com")
        with pytest.raises(RateLimitedError, match="signin-ip"):
            service.login("fresh@acme.com", PASSWORD, IP)
        _fail_login(service, "fresh@acme.com", "198.51.100.9")  # another IP is unaffected


def test_an_email_is_limited_across_ips(repos: Repositories, clock: Clock) -> None:
    service = AuthService(
        repos,
        AuthPolicy(clock=clock, signin_limit_per_email=4, signin_limit_per_email_and_ip=2),
    )
    with patch("dndlabs.auth.service.verify_against_dummy"):
        for ip in ("10.0.0.1", "10.0.0.2"):
            for _ in range(2):
                _fail_login(service, "ada@acme.com", ip)
            # An IP refused by its own (email, IP) limit adds nothing to the
            # email's limit, so one attacker cannot exhaust it alone.
            with pytest.raises(RateLimitedError, match="signin-email-ip"):
                service.login("ada@acme.com", PASSWORD, ip)
        with pytest.raises(RateLimitedError, match="signin-email limit"):
            service.login("ada@acme.com", PASSWORD, "10.0.0.3")


def test_successful_login_is_not_counted_and_clears_the_email_limits(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    _admin_session(service, org)
    for _ in range(4):
        _fail_login(service, "ada@acme.com")
    service.login("ada@acme.com", PASSWORD, IP)
    counters = repos.rate_limits.items  # type: ignore[attr-defined]
    # Only the IP's counter is left: its 4 failures (the success was refunded).
    assert [(b.split(":")[0], c) for b, (_, c, _) in counters.items()] == [("signin-ip", 4)]
    for _ in range(5):  # a fresh allowance for the email
        _fail_login(service, "ada@acme.com")


def test_counters_store_digests_not_ips_or_emails(
    service: AuthService, repos: Repositories
) -> None:
    _fail_login(service, "nobody@acme.com")
    buckets = " ".join(repos.rate_limits.items)  # type: ignore[attr-defined]
    assert "nobody" not in buckets and IP not in buckets


def test_login_purges_expired_counters(
    service: AuthService, repos: Repositories, clock: Clock
) -> None:
    _fail_login(service, "nobody@acme.com")
    clock.advance(timedelta(minutes=15))
    _fail_login(service, "other@acme.com")
    counters = repos.rate_limits.items  # type: ignore[attr-defined]
    assert all(start == clock.now for start, _, _ in counters.values())
    assert len(counters) == 3


# --- authentication failures per client IP ------------------------------------


def _limited_service(repos: Repositories, clock: Clock) -> AuthService:
    return AuthService(repos, AuthPolicy(clock=clock, auth_failure_limit_per_ip=3))


def test_api_key_failures_are_limited_before_argon2(
    repos: Repositories, clock: Clock, org: Organization
) -> None:
    service = _limited_service(repos, clock)
    created = service.issue_key(org)
    wrong = created.raw_key[:-4] + "xxxx"
    for raw in (wrong, "ddl_live_unknownprefix", wrong):
        with pytest.raises(InvalidApiKeyError):
            service.resolve_api_key(raw, IP)

    with (
        patch("dndlabs.auth.service.verify_key") as verify,
        pytest.raises(RateLimitedError) as limited,
    ):
        service.resolve_api_key(wrong, IP)
    verify.assert_not_called()  # an attacker cannot force more Argon2 hashes
    assert limited.value.retry_after_seconds == 15 * 60
    with pytest.raises(RateLimitedError):
        service.resolve_api_key("ddl_live_unknownprefix", IP)

    # The same key from another IP is unaffected; after the window, so is this IP.
    assert service.resolve_api_key(created.raw_key, "198.51.100.9").org_id == org.id
    clock.advance(timedelta(minutes=15))
    assert service.resolve_api_key(created.raw_key, IP).org_id == org.id


def test_a_valid_api_key_is_never_counted(
    repos: Repositories, clock: Clock, org: Organization
) -> None:
    service = _limited_service(repos, clock)
    created = service.issue_key(org)
    for _ in range(10):
        service.resolve_api_key(created.raw_key, IP)
    assert repos.rate_limits.items == {}  # type: ignore[attr-defined]


def test_session_failures_are_limited_but_a_valid_session_is_never_refused(
    repos: Repositories, clock: Clock, org: Organization
) -> None:
    service = _limited_service(repos, clock)
    token = _admin_session(service, org)
    for bad in ("garbage", "ddl_sess_unknown", "ddl_sess_unknown"):
        with pytest.raises(NotAuthenticatedError):
            service.resolve_session(bad, IP)
    with pytest.raises(RateLimitedError):
        service.resolve_session("ddl_sess_unknown", IP)
    assert service.resolve_session(token, IP).email == "ada@acme.com"


def test_login_upgrades_an_outdated_hash(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    _admin_session(service, org)
    users: FakeUsers = repos.users  # type: ignore[assignment]
    before = users.get_credentials("ada@acme.com")
    assert before is not None
    with patch("dndlabs.auth.service.needs_rehash", return_value=True):
        service.login("ada@acme.com", PASSWORD, IP)
    after = users.get_credentials("ada@acme.com")
    assert after is not None and after.password_hash != before.password_hash
    service.login("ada@acme.com", PASSWORD, IP)  # the new hash verifies


def test_login_purges_long_expired_sessions(
    service: AuthService, org: Organization, repos: Repositories, clock: Clock
) -> None:
    old = _admin_session(service, org)
    clock.advance(timedelta(days=31))
    service.login("ada@acme.com", PASSWORD, IP)
    assert all(s.expires_at > clock.now - timedelta(days=30) for s in repos.sessions.items.values())  # type: ignore[attr-defined]
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(old, IP)


# --- sessions -----------------------------------------------------------------


@pytest.mark.parametrize("token", ["", "ddl_live_notasession", "ddl_sess_unknown"])
def test_unknown_session_token_is_rejected(service: AuthService, token: str) -> None:
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token, IP)


def test_session_of_a_removed_user_is_rejected(
    service: AuthService, org: Organization, repos: Repositories
) -> None:
    token = _admin_session(service, org)
    repos.users.items.clear()  # type: ignore[attr-defined]
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token, IP)


def test_session_expires(service: AuthService, org: Organization, clock: Clock) -> None:
    token = _admin_session(service, org)
    clock.advance(timedelta(hours=12))
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(token, IP)


def test_logout_revokes_only_the_calling_session(service: AuthService, org: Organization) -> None:
    first = _admin_session(service, org)
    second = service.login("ada@acme.com", PASSWORD, IP).token
    service.logout(service.resolve_session(first, IP))
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(first, IP)
    assert service.resolve_session(second, IP).email == "ada@acme.com"


def test_logout_requires_a_session(service: AuthService, org: Organization) -> None:
    ctx = service.resolve_api_key(service.issue_key(org).raw_key, IP)
    with pytest.raises(ForbiddenError):
        service.logout(ctx)


def test_change_password_ends_other_sessions(service: AuthService, org: Organization) -> None:
    current = _admin_session(service, org)
    other = service.login("ada@acme.com", PASSWORD, IP).token
    new_password = "a different long passphrase"

    service.change_password(service.resolve_session(current, IP), PASSWORD, new_password)

    assert service.resolve_session(current, IP).email == "ada@acme.com"
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(other, IP)
    with pytest.raises(InvalidCredentialsError):
        service.login("ada@acme.com", PASSWORD, IP)
    service.login("ada@acme.com", new_password, IP)


def test_change_password_checks_the_current_password_and_policy(
    service: AuthService, org: Organization
) -> None:
    ctx = service.resolve_session(_admin_session(service, org), IP)
    with pytest.raises(ForbiddenError, match="current password"):
        service.change_password(ctx, "not the password", "a different long passphrase")
    with pytest.raises(PasswordPolicyError):
        service.change_password(ctx, PASSWORD, "ada@acme.com")


def test_change_password_requires_a_session(service: AuthService, org: Organization) -> None:
    ctx: OrgContext = service.resolve_api_key(service.issue_key(org).raw_key, IP)
    with pytest.raises(ForbiddenError):
        service.change_password(ctx, PASSWORD, "a different long passphrase")


def test_default_policy_is_used_when_none_is_given(repos: Repositories) -> None:
    service = AuthService(repos)
    org = repos.organizations.create(Organization(name="Acme"))
    assert service.invite_admin(org, "a@b.co").accept_url.startswith("http://localhost:5173/")
    assert isinstance(repos.api_keys, FakeApiKeys)


# --- members ------------------------------------------------------------------


def _member_session(service: AuthService, admin: OrgContext, email: str, role: Role) -> OrgContext:
    invitation = service.invite(admin, InvitationCreate(email=email, role=role))
    return service.resolve_session(service.accept_invitation(invitation.token, PASSWORD).token, IP)


def test_admin_lists_members_and_changes_roles(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    assert [m.email for m in service.list_members(admin)] == ["ada@acme.com", "bob@acme.com"]

    promoted = service.set_member_role(admin, bob.user_id, Role.ADMIN)  # type: ignore[arg-type]
    assert promoted.role is Role.ADMIN
    assert service.resolve_session(_login(service, "bob@acme.com"), IP).role is Role.ADMIN


def test_the_last_admin_cannot_be_demoted_or_removed(
    service: AuthService, org: Organization
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    with pytest.raises(ConflictError, match="at least one admin"):
        service.set_member_role(admin, admin.user_id, Role.MEMBER)  # type: ignore[arg-type]
    key = service.resolve_api_key(service.issue_key(org).raw_key, IP)
    with pytest.raises(ConflictError, match="at least one admin"):
        service.remove_member(key, admin.user_id)  # type: ignore[arg-type]

    second = _member_session(service, admin, "cleo@acme.com", Role.ADMIN)
    service.set_member_role(admin, admin.user_id, Role.MEMBER)  # type: ignore[arg-type]
    assert service.resolve_session(_login(service, "ada@acme.com"), IP).role is Role.MEMBER
    assert second.role is Role.ADMIN


def test_removing_a_member_ends_their_sessions(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    bob_token = _login(service, "bob@acme.com")

    service.remove_member(admin, bob.user_id)  # type: ignore[arg-type]

    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(bob_token, IP)
    with pytest.raises(InvalidCredentialsError):
        service.login("bob@acme.com", PASSWORD, IP)
    # The email can be invited again.
    service.invite(admin, InvitationCreate(email="bob@acme.com"))


def test_admins_cannot_remove_themselves(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    with pytest.raises(ForbiddenError, match="yourself"):
        service.remove_member(admin, admin.user_id)  # type: ignore[arg-type]


def test_members_cannot_manage_members(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    for action in (
        lambda: service.list_members(bob),
        lambda: service.set_member_role(bob, admin.user_id, Role.MEMBER),  # type: ignore[arg-type]
        lambda: service.remove_member(bob, admin.user_id),  # type: ignore[arg-type]
        lambda: service.issue_password_reset(bob, admin.user_id),  # type: ignore[arg-type]
        lambda: service.list_pending_invitations(bob),
    ):
        with pytest.raises(ForbiddenError):
            action()


def test_managing_a_user_of_another_org_is_not_found(
    service: AuthService, repos: Repositories
) -> None:
    acme = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    acme_admin = service.resolve_session(_admin_session(service, acme, "ada@acme.com"), IP)
    other_admin = service.resolve_session(_admin_session(service, other, "otto@other.com"), IP)
    with pytest.raises(NotFoundError):
        service.remove_member(acme_admin, other_admin.user_id)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        service.issue_password_reset(acme_admin, other_admin.user_id)  # type: ignore[arg-type]


# --- pending invitations ------------------------------------------------------


def test_pending_invitations_can_be_listed_and_revoked(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    first = service.invite(admin, InvitationCreate(email="bob@acme.com"))
    second = service.invite(admin, InvitationCreate(email="cleo@acme.com"))
    assert [i.email for i in service.list_pending_invitations(admin)] == [
        "cleo@acme.com",
        "bob@acme.com",
    ]

    service.revoke_invitation(admin, first.id)

    assert [i.id for i in service.list_pending_invitations(admin)] == [second.id]
    with pytest.raises(InvitationInvalidError):
        service.accept_invitation(first.token, PASSWORD)
    with pytest.raises(NotFoundError):
        service.revoke_invitation(admin, first.id)  # already revoked
    clock.advance(timedelta(hours=72))
    assert service.list_pending_invitations(admin) == []


# --- password reset -----------------------------------------------------------


def test_password_reset_sets_a_new_password_and_ends_sessions(
    service: AuthService, org: Organization
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    old_session = _login(service, "bob@acme.com")

    reset = service.issue_password_reset(admin, bob.user_id)  # type: ignore[arg-type]
    assert reset.reset_url == f"https://app.example/reset#token={reset.token}"
    preview, preview_org = service.preview_password_reset(reset.token)
    assert (preview.email, preview_org.name) == ("bob@acme.com", "Acme")

    session = service.reset_password(reset.token, "a brand new passphrase")

    assert session.user.email == "bob@acme.com"
    with pytest.raises(NotAuthenticatedError):
        service.resolve_session(old_session, IP)
    with pytest.raises(InvalidCredentialsError):
        service.login("bob@acme.com", PASSWORD, IP)
    service.login("bob@acme.com", "a brand new passphrase", IP)
    with pytest.raises(InvitationInvalidError):
        service.reset_password(reset.token, "another new passphrase")  # single use


def test_password_reset_lifts_the_sign_in_limits(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    for _ in range(5):
        _fail_login(service, "bob@acme.com")
    with pytest.raises(RateLimitedError):
        service.login("bob@acme.com", PASSWORD, IP)

    reset = service.issue_password_reset(admin, bob.user_id)  # type: ignore[arg-type]
    service.reset_password(reset.token, "a brand new passphrase")
    service.login("bob@acme.com", "a brand new passphrase", IP)


def test_a_new_reset_link_supersedes_the_previous_one(
    service: AuthService, org: Organization
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    first = service.issue_password_reset(admin, bob.user_id)  # type: ignore[arg-type]
    second = service.issue_password_reset(admin, bob.user_id)  # type: ignore[arg-type]
    with pytest.raises(InvitationInvalidError):
        service.reset_password(first.token, "a brand new passphrase")
    service.reset_password(second.token, "a brand new passphrase")


def test_reset_links_expire_after_24_hours(
    service: AuthService, org: Organization, clock: Clock
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    reset = service.issue_password_reset(admin, admin.user_id)  # type: ignore[arg-type]
    clock.advance(timedelta(hours=24))
    with pytest.raises(InvitationInvalidError):
        service.preview_password_reset(reset.token)


def test_reset_and_invitation_tokens_are_not_interchangeable(
    service: AuthService, org: Organization
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    invitation = service.invite(admin, InvitationCreate(email="bob@acme.com"))
    reset = service.issue_password_reset(admin, admin.user_id)  # type: ignore[arg-type]
    with pytest.raises(InvitationInvalidError):
        service.reset_password(invitation.token, "a brand new passphrase")
    with pytest.raises(InvitationInvalidError):
        service.accept_invitation(reset.token, "a brand new passphrase")
    with pytest.raises(InvitationInvalidError):
        service.preview_invitation(reset.token)


def test_reset_policy_is_enforced_and_the_link_survives_a_weak_password(
    service: AuthService, org: Organization
) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    reset = service.issue_password_reset(admin, admin.user_id)  # type: ignore[arg-type]
    with pytest.raises(PasswordPolicyError):
        service.reset_password(reset.token, "short")
    service.reset_password(reset.token, "a brand new passphrase")


def test_reset_for_a_removed_member_fails(service: AuthService, org: Organization) -> None:
    admin = service.resolve_session(_admin_session(service, org), IP)
    bob = _member_session(service, admin, "bob@acme.com", Role.MEMBER)
    reset = service.issue_password_reset(admin, bob.user_id)  # type: ignore[arg-type]
    service.remove_member(admin, bob.user_id)  # type: ignore[arg-type]
    with pytest.raises(InvitationInvalidError):
        service.reset_password(reset.token, "a brand new passphrase")


def test_operator_reset_by_email(service: AuthService, repos: Repositories) -> None:
    acme = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    _admin_session(service, acme, "ada@acme.com")
    reset = service.issue_password_reset_for_email(acme, "ADA@acme.com")
    assert reset.email == "ada@acme.com"
    service.reset_password(reset.token, "a brand new passphrase")
    with pytest.raises(NotFoundError):
        service.issue_password_reset_for_email(other, "ada@acme.com")
    with pytest.raises(NotFoundError):
        service.issue_password_reset_for_email(acme, "nobody@acme.com")


def _login(service: AuthService, email: str) -> str:
    return service.login(email, PASSWORD, IP).token
