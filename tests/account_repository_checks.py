"""Behavioural checks for the account repositories, shared by the SQLite and PostgreSQL suites."""

from datetime import UTC, datetime, timedelta

import pytest

from dndlabs.core.exceptions import ConflictError, InvitationInvalidError, NotFoundError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    Invitation,
    InvitationPurpose,
    Organization,
    Role,
    User,
    UserSession,
)


def check_users(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    user = repos.users.create(User(org_id=org.id, email="ada@acme.com", role=Role.ADMIN), "h1")

    creds = repos.users.get_credentials("ada@acme.com")
    assert creds is not None
    assert creds.user == user
    assert (creds.password_hash, creds.failed_login_count, creds.locked_until) == ("h1", 0, None)
    assert repos.users.get_credentials("nobody@acme.com") is None
    assert repos.users.email_exists("ada@acme.com")
    assert not repos.users.email_exists("nobody@acme.com")

    assert repos.users.get(org.id, user.id).user.email == "ada@acme.com"
    with pytest.raises(NotFoundError):
        repos.users.get(other.id, user.id)  # tenant-scoped

    with pytest.raises(ConflictError):
        repos.users.create(User(org_id=other.id, email="ada@acme.com"), "h2")

    repos.users.set_password(org.id, user.id, "h3")
    with pytest.raises(NotFoundError):
        repos.users.set_password(other.id, user.id, "h4")
    assert repos.users.get(org.id, user.id).password_hash == "h3"


def check_login_counters(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    user = repos.users.create(User(org_id=org.id, email="ada@acme.com"), "h")
    lock_until = datetime(2030, 1, 1, tzinfo=UTC)

    repos.users.record_login_failure(user.id, 3, lock_until)
    repos.users.record_login_failure(user.id, 3, lock_until)
    assert repos.users.get(org.id, user.id).failed_login_count == 2
    repos.users.record_login_failure(user.id, 3, lock_until)
    locked = repos.users.get(org.id, user.id)
    assert (locked.failed_login_count, locked.locked_until) == (0, lock_until)

    repos.users.record_login_success(user.id)
    cleared = repos.users.get(org.id, user.id)
    assert (cleared.failed_login_count, cleared.locked_until) == (0, None)


def check_sessions(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    user = repos.users.create(User(org_id=org.id, email="ada@acme.com"), "h")
    now = datetime.now(UTC)
    first = repos.sessions.create(
        UserSession(user_id=user.id, org_id=org.id, expires_at=now + timedelta(hours=1)), "a" * 64
    )
    second = repos.sessions.create(
        UserSession(user_id=user.id, org_id=org.id, expires_at=now + timedelta(hours=1)), "b" * 64
    )
    stale = repos.sessions.create(
        UserSession(user_id=user.id, org_id=org.id, expires_at=now - timedelta(days=40)), "c" * 64
    )

    found = repos.sessions.get_by_token_hash("a" * 64)
    assert found is not None
    assert (found.id, found.revoked_at) == (first.id, None)
    assert abs(found.expires_at - first.expires_at) < timedelta(seconds=1)
    assert repos.sessions.get_by_token_hash("d" * 64) is None

    repos.sessions.revoke(other.id, first.id)  # wrong org: no effect
    assert repos.sessions.get_by_token_hash("a" * 64).revoked_at is None  # type: ignore[union-attr]
    repos.sessions.revoke(org.id, first.id)
    assert repos.sessions.get_by_token_hash("a" * 64).revoked_at is not None  # type: ignore[union-attr]

    assert repos.sessions.revoke_all_for_user(org.id, user.id, except_session_id=second.id) == 1
    assert repos.sessions.get_by_token_hash("b" * 64).revoked_at is None  # type: ignore[union-attr]
    assert repos.sessions.revoke_all_for_user(org.id, user.id) == 1

    assert repos.sessions.delete_expired(now - timedelta(days=30)) == 1
    assert repos.sessions.get_by_token_hash("c" * 64) is None
    assert stale.id != first.id


def check_invitations(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    now = datetime.now(UTC)
    invitation = repos.invitations.create(
        Invitation(
            org_id=org.id, email="bob@acme.com", role=Role.MEMBER, expires_at=now + timedelta(1)
        ),
        "e" * 64,
    )
    found = repos.invitations.get_by_token_hash("e" * 64)
    assert found is not None
    assert (found.id, found.email, found.role, found.accepted_at) == (
        invitation.id,
        "bob@acme.com",
        Role.MEMBER,
        None,
    )
    assert repos.invitations.get_by_token_hash("f" * 64) is None

    user = repos.invitations.accept(
        invitation, User(org_id=org.id, email="bob@acme.com", role=Role.MEMBER), "h"
    )
    assert repos.users.get(org.id, user.id).user.role is Role.MEMBER
    accepted = repos.invitations.get_by_token_hash("e" * 64)
    assert accepted is not None and accepted.accepted_at is not None

    with pytest.raises(InvitationInvalidError):
        repos.invitations.accept(invitation, User(org_id=org.id, email="bob2@acme.com"), "h")
    assert not repos.users.email_exists("bob2@acme.com")


def check_accept_is_atomic(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    repos.users.create(User(org_id=org.id, email="taken@acme.com"), "h")
    invitation = repos.invitations.create(
        Invitation(
            org_id=org.id,
            email="taken@acme.com",
            role=Role.ADMIN,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
        "g" * 64,
    )
    with pytest.raises(ConflictError):
        repos.invitations.accept(invitation, User(org_id=org.id, email="taken@acme.com"), "h")
    unused = repos.invitations.get_by_token_hash("g" * 64)
    assert unused is not None and unused.accepted_at is None  # rolled back


def check_member_management(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    other = repos.organizations.create(Organization(name="OtherCo"))
    ada = repos.users.create(User(org_id=org.id, email="ada@acme.com", role=Role.ADMIN), "h")
    bob = repos.users.create(User(org_id=org.id, email="bob@acme.com"), "h")
    repos.users.create(User(org_id=other.id, email="otto@other.com"), "h")
    assert [u.email for u in repos.users.list_members(org.id)] == ["ada@acme.com", "bob@acme.com"]

    assert repos.users.set_role(org.id, bob.id, Role.ADMIN).role is Role.ADMIN
    with pytest.raises(NotFoundError):
        repos.users.set_role(other.id, bob.id, Role.MEMBER)

    now = datetime.now(UTC)
    repos.sessions.create(
        UserSession(user_id=bob.id, org_id=org.id, expires_at=now + timedelta(hours=1)), "s" * 64
    )
    invited = repos.invitations.create(
        Invitation(
            org_id=org.id,
            email="cleo@acme.com",
            role=Role.MEMBER,
            created_by=bob.id,
            expires_at=now + timedelta(days=1),
        ),
        "i" * 64,
    )
    with pytest.raises(NotFoundError):
        repos.users.delete(other.id, bob.id)
    repos.users.delete(org.id, bob.id)
    assert [u.id for u in repos.users.list_members(org.id)] == [ada.id]
    assert repos.sessions.get_by_token_hash("s" * 64) is None
    kept = repos.invitations.get_by_token_hash("i" * 64)
    assert kept is not None and kept.created_by is None and kept.id == invited.id


def check_pending_revoke_and_reset(repos: Repositories) -> None:
    org = repos.organizations.create(Organization(name="Acme"))
    user = repos.users.create(User(org_id=org.id, email="bob@acme.com"), "old-hash")
    now = datetime.now(UTC)
    repos.users.record_login_failure(user.id, 1, now + timedelta(hours=1))  # locked
    repos.sessions.create(
        UserSession(user_id=user.id, org_id=org.id, expires_at=now + timedelta(hours=1)), "s" * 64
    )

    def token(
        email: str, purpose: InvitationPurpose, digest: str, expires_in: timedelta = timedelta(1)
    ) -> Invitation:
        return repos.invitations.create(
            Invitation(
                org_id=org.id,
                email=email,
                role=Role.MEMBER,
                purpose=purpose,
                expires_at=now + expires_in,
            ),
            digest,
        )

    join = token("cleo@acme.com", InvitationPurpose.JOIN, "a" * 64)
    token("gone@acme.com", InvitationPurpose.JOIN, "b" * 64, expires_in=-timedelta(1))
    reset = token("bob@acme.com", InvitationPurpose.PASSWORD_RESET, "c" * 64)

    pending = repos.invitations.list_pending(org.id, InvitationPurpose.JOIN, now)
    assert [i.id for i in pending] == [join.id]
    resets = repos.invitations.list_pending(org.id, InvitationPurpose.PASSWORD_RESET, now)
    assert [(i.id, i.purpose) for i in resets] == [(reset.id, InvitationPurpose.PASSWORD_RESET)]

    repos.invitations.revoke(org.id, join.id)
    revoked = repos.invitations.get_by_token_hash("a" * 64)
    assert revoked is not None and revoked.revoked_at is not None
    assert repos.invitations.list_pending(org.id, InvitationPurpose.JOIN, now) == []
    with pytest.raises(NotFoundError):
        repos.invitations.revoke(org.id, join.id)
    with pytest.raises(InvitationInvalidError):  # a revoked invitation cannot be accepted
        repos.invitations.accept(revoked, User(org_id=org.id, email="cleo@acme.com"), "h")

    reset_user = repos.invitations.redeem_password_reset(reset, "new-hash")
    assert reset_user.id == user.id
    creds = repos.users.get(org.id, user.id)
    assert (creds.password_hash, creds.failed_login_count, creds.locked_until) == (
        "new-hash",
        0,
        None,
    )
    assert repos.sessions.get_by_token_hash("s" * 64) is None
    with pytest.raises(InvitationInvalidError):
        repos.invitations.redeem_password_reset(reset, "newer-hash")

    orphan = token("nobody@acme.com", InvitationPurpose.PASSWORD_RESET, "d" * 64)
    with pytest.raises(InvitationInvalidError):
        repos.invitations.redeem_password_reset(orphan, "h")
    unused = repos.invitations.get_by_token_hash("d" * 64)
    assert unused is not None and unused.accepted_at is None  # rolled back


ALL_CHECKS = (
    check_users,
    check_login_counters,
    check_sessions,
    check_invitations,
    check_accept_is_atomic,
    check_member_management,
    check_pending_revoke_and_reset,
)
