"""SQLAlchemy implementations of the ``core.protocols`` repositories.

Every method that reads or writes a specific entity takes ``org_id`` and
filters by it — this is the tenant-isolation boundary. No method accepts a
caller-supplied override; ``org_id`` always comes from the authenticated
request context, never from a request body or query string. The unscoped
exceptions are the authentication lookups (by key prefix, token digest or
email, which find the org), the run worker's queue methods, and
cross-org housekeeping; ``core.protocols`` lists them.

Every write runs inside a ``SessionFactory.transaction``, which commits on
success and rolls back on any error.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, delete, func, or_, select, text, update
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from dndlabs.core.exceptions import (
    ConflictError,
    InvitationInvalidError,
    NotFoundError,
    StorageError,
)
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    FINISHED_STATUSES,
    ApiKeyRecord,
    AssayFormat,
    ColumnRole,
    ControlType,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentResult,
    FeatureVector,
    Invitation,
    InvitationPurpose,
    MappingTemplate,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    Role,
    RunProgress,
    RunStage,
    RunStatus,
    SourceSpec,
    SourceType,
    StoredFeatures,
    Upload,
    UploadFormat,
    User,
    UserCredentials,
    UserSession,
    utcnow,
)
from dndlabs.storage.database import SessionFactory
from dndlabs.storage.models import (
    ApiKeyRow,
    DatasetRow,
    EnrichmentResultRow,
    FeatureVectorRow,
    InvitationRow,
    MappingTemplateRow,
    NormalizedRecordRow,
    OrganizationRow,
    QualityReportRow,
    RunRow,
    UploadRow,
    UserRow,
    UserSessionRow,
    ValidationIssueRow,
)


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to naive datetimes returned by SQLite.

    Timestamps are written as aware UTC, but SQLite has no timezone type
    and returns it naive; comparing that with an aware ``utcnow()`` would
    raise. PostgreSQL's ``timestamptz`` values pass through unchanged.
    """
    return value if value.tzinfo else value.replace(tzinfo=UTC)


#: Values per SQL ``IN`` list, well under PostgreSQL's parameter limit.
_IN_CHUNK = 5_000


class SqlOrganizationRepository:
    """Stores organizations."""

    def __init__(self, sessions: SessionFactory, expected_revision: str | None = None) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
            expected_revision: The Alembic revision the schema must be at for
                :meth:`ping` to pass, or ``None`` when the schema is not
                managed by migrations (``create_all`` in development).
        """
        self._sessions = sessions
        self._expected_revision = expected_revision

    def create(self, org: Organization) -> Organization:
        """Insert a new organization.

        Args:
            org: The organization to store.

        Returns:
            The stored organization.
        """
        with self._sessions.transaction() as session:
            session.add(
                OrganizationRow(
                    id=org.id, name=org.name, created_at=org.created_at, is_active=org.is_active
                )
            )
        return org

    def get(self, org_id: uuid.UUID) -> Organization:
        """Fetch an organization by id.

        Args:
            org_id: Organization identifier.

        Returns:
            The organization.

        Raises:
            NotFoundError: If the organization does not exist.
        """
        with self._sessions.transaction() as session:
            row = session.get(OrganizationRow, org_id)
            if row is None:
                raise NotFoundError(f"organization {org_id} not found")
            return Organization(
                id=row.id,
                name=row.name,
                created_at=_as_utc(row.created_at),
                is_active=row.is_active,
            )

    def ping(self) -> None:
        """Verify storage is reachable and migrated.

        Raises:
            StorageError: If the database is unreachable, the
                ``organizations`` table is missing, or the schema is not at
                the expected migration revision.
        """
        with self._sessions.transaction() as session:
            session.execute(select(OrganizationRow.id).limit(1))
            if self._expected_revision is None:
                return
            # Reachable is not ready: a deploy whose migrations have not run
            # (or failed) must not take traffic against an older schema.
            revisions: set[str] = set(
                session.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
        if revisions != {self._expected_revision}:
            found = ", ".join(sorted(revisions)) or "none"
            raise StorageError(f"schema is at revision {found}, expected {self._expected_revision}")


class SqlApiKeyRepository:
    """Stores hashed API keys."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, org_id: uuid.UUID, prefix: str, hashed_key: str) -> ApiKeyRecord:
        """Store a newly issued key.

        Args:
            org_id: Owning organization.
            prefix: Non-secret lookup prefix.
            hashed_key: Argon2 hash of the raw secret.

        Returns:
            The stored key record.
        """
        row = ApiKeyRow(
            id=uuid.uuid4(),
            org_id=org_id,
            prefix=prefix,
            hashed_key=hashed_key,
            created_at=datetime.now(UTC),
        )
        with self._sessions.transaction() as session:
            session.add(row)
            session.flush()
            return _key_from_row(row)

    def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        """Look up a key by its prefix for verification.

        Unscoped by design: this is how a request's org is found.

        Args:
            prefix: Non-secret lookup prefix.

        Returns:
            The key record (with hash, for internal verification use), or
            ``None``.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(select(ApiKeyRow).where(ApiKeyRow.prefix == prefix)).first()
            return _key_from_row(row) if row else None

    def get_hash(self, prefix: str) -> str | None:
        """Fetch the stored hash for a prefix (internal to auth verification).

        Args:
            prefix: Non-secret lookup prefix.

        Returns:
            The hash, or ``None`` if the prefix is unknown.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(select(ApiKeyRow).where(ApiKeyRow.prefix == prefix)).first()
            return row.hashed_key if row else None

    def touch_last_used(self, key_id: uuid.UUID) -> None:
        """Record that a key was just used.

        Args:
            key_id: Key identifier.
        """
        with self._sessions.transaction() as session:
            row = session.get(ApiKeyRow, key_id)
            if row is not None:
                row.last_used_at = datetime.now(UTC)

    def revoke(self, org_id: uuid.UUID, key_id: uuid.UUID) -> None:
        """Revoke a key belonging to ``org_id``.

        Args:
            org_id: Owning organization (enforced).
            key_id: Key to revoke.

        Raises:
            NotFoundError: If the key does not exist for this org.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(ApiKeyRow).where(ApiKeyRow.id == key_id, ApiKeyRow.org_id == org_id)
            ).first()
            if row is None:
                raise NotFoundError(f"api key {key_id} not found for org {org_id}")
            row.revoked_at = datetime.now(UTC)


def _key_from_row(row: ApiKeyRow) -> ApiKeyRecord:
    """Convert a key row to its contract."""
    return ApiKeyRecord(
        id=row.id,
        org_id=row.org_id,
        prefix=row.prefix,
        created_at=_as_utc(row.created_at),
        last_used_at=_as_utc(row.last_used_at) if row.last_used_at else None,
        revoked_at=_as_utc(row.revoked_at) if row.revoked_at else None,
    )


_EMAIL_TAKEN = "an account with this email already exists"


class SqlUserRepository:
    """Stores user accounts and their sign-in state."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, user: User, password_hash: str) -> User:
        """Insert a new user.

        Args:
            user: The user to store.
            password_hash: Argon2 hash of the password.

        Returns:
            The stored user.

        Raises:
            ConflictError: If an account with this email already exists.
        """
        with self._sessions.transaction() as session:
            _insert_user(session, user, password_hash)
        return user

    def get_credentials(self, email: str) -> UserCredentials | None:
        """Look up a user and their sign-in state by normalized email.

        Unscoped by design: emails are unique across orgs and sign-in is by
        email alone.

        Args:
            email: Normalized email address.

        Returns:
            The credentials, or ``None``.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(select(UserRow).where(UserRow.email == email)).first()
            return _credentials_from_row(row) if row else None

    def get(self, org_id: uuid.UUID, user_id: uuid.UUID) -> UserCredentials:
        """Fetch a user of ``org_id`` with their sign-in state.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.

        Returns:
            The credentials.

        Raises:
            NotFoundError: If the user does not exist in this org.
        """
        with self._sessions.transaction() as session:
            row = _user_row(session, org_id, user_id)
            return _credentials_from_row(row)

    def email_exists(self, email: str) -> bool:
        """Whether any account uses ``email``.

        Args:
            email: Normalized email address.

        Returns:
            True if an account exists.
        """
        with self._sessions.transaction() as session:
            return (
                session.scalars(select(UserRow.id).where(UserRow.email == email)).first()
                is not None
            )

    def record_login_failure(
        self, user_id: uuid.UUID, max_attempts: int, lock_until: datetime
    ) -> None:
        """Count a failed sign-in, locking the account once ``max_attempts`` is reached.

        Args:
            user_id: User identifier.
            max_attempts: Failures that trigger a lock.
            lock_until: When a lock triggered by this failure expires.
        """
        with self._sessions.transaction() as session:
            # Incremented in SQL, not read-modify-write in Python, so
            # concurrent failed sign-ins are all counted.
            session.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(failed_login_count=UserRow.failed_login_count + 1)
            )
            count = session.scalars(
                select(UserRow.failed_login_count).where(UserRow.id == user_id)
            ).first()
            if count is not None and count >= max_attempts:
                session.execute(
                    update(UserRow)
                    .where(UserRow.id == user_id)
                    .values(failed_login_count=0, locked_until=lock_until)
                )

    def record_login_success(self, user_id: uuid.UUID) -> None:
        """Reset the failure counter and any lock.

        Args:
            user_id: User identifier.
        """
        with self._sessions.transaction() as session:
            session.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(failed_login_count=0, locked_until=None)
            )

    def list_members(self, org_id: uuid.UUID) -> list[User]:
        """List an organization's users, oldest first.

        Args:
            org_id: Organization (enforced).

        Returns:
            The users.
        """
        with self._sessions.transaction() as session:
            rows = session.scalars(
                select(UserRow).where(UserRow.org_id == org_id).order_by(UserRow.created_at)
            )
            return [_credentials_from_row(row).user for row in rows]

    def set_role(self, org_id: uuid.UUID, user_id: uuid.UUID, role: Role) -> User:
        """Change a user's role.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.
            role: The new role.

        Returns:
            The updated user.

        Raises:
            NotFoundError: If the user does not exist in this org.
        """
        with self._sessions.transaction() as session:
            row = _user_row(session, org_id, user_id)
            row.role = role.value
            return _credentials_from_row(row).user

    def delete(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete a user and their sessions.

        Sessions are deleted explicitly rather than relying on ``ON DELETE
        CASCADE``, which SQLite only honours with its foreign-keys pragma.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.

        Raises:
            NotFoundError: If the user does not exist in this org.
        """
        with self._sessions.transaction() as session:
            row = _user_row(session, org_id, user_id)
            session.execute(delete(UserSessionRow).where(UserSessionRow.user_id == user_id))
            session.execute(
                update(InvitationRow)
                .where(InvitationRow.created_by == user_id)
                .values(created_by=None)
            )
            session.delete(row)

    def set_password(self, org_id: uuid.UUID, user_id: uuid.UUID, password_hash: str) -> None:
        """Replace a user's password hash.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.
            password_hash: New Argon2 hash.

        Raises:
            NotFoundError: If the user does not exist in this org.
        """
        with self._sessions.transaction() as session:
            row = _user_row(session, org_id, user_id)
            row.password_hash = password_hash
            row.password_changed_at = datetime.now(UTC)


def _user_row(session: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> UserRow:
    """Fetch a user row scoped to ``org_id``, or raise ``NotFoundError``."""
    row = session.scalars(
        select(UserRow).where(UserRow.id == user_id, UserRow.org_id == org_id)
    ).first()
    if row is None:
        raise NotFoundError(f"user {user_id} not found for org {org_id}")
    return row


def _insert_user(session: Session, user: User, password_hash: str) -> None:
    """Insert a user row, translating a duplicate email into ``ConflictError``."""
    if session.scalars(select(UserRow.id).where(UserRow.email == user.email)).first():
        raise ConflictError(_EMAIL_TAKEN)
    session.add(
        UserRow(
            id=user.id,
            org_id=user.org_id,
            email=user.email,
            password_hash=password_hash,
            role=user.role.value,
            created_at=user.created_at,
            password_changed_at=user.created_at,
            failed_login_count=0,
        )
    )
    try:
        session.flush()
    except IntegrityError as exc:  # a concurrent insert won the unique index
        raise ConflictError(_EMAIL_TAKEN) from exc


def _credentials_from_row(row: UserRow) -> UserCredentials:
    """Convert a user row to its credentials contract."""
    return UserCredentials(
        user=User(
            id=row.id,
            org_id=row.org_id,
            email=row.email,
            role=Role(row.role),
            created_at=_as_utc(row.created_at),
        ),
        password_hash=row.password_hash,
        failed_login_count=row.failed_login_count,
        locked_until=_as_utc(row.locked_until) if row.locked_until else None,
    )


class SqlSessionRepository:
    """Stores sign-in sessions by token digest."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, session: UserSession, token_hash: str) -> UserSession:
        """Store a new session.

        Args:
            session: The session metadata.
            token_hash: SHA-256 hex digest of the bearer token.

        Returns:
            The stored session.
        """
        with self._sessions.transaction() as db:
            db.add(
                UserSessionRow(
                    id=session.id,
                    user_id=session.user_id,
                    org_id=session.org_id,
                    token_hash=token_hash,
                    created_at=session.created_at,
                    expires_at=session.expires_at,
                )
            )
        return session

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        """Look up a session by its token digest.

        Unscoped by design: this is how a request's org is found.

        Args:
            token_hash: SHA-256 hex digest of the presented token.

        Returns:
            The session, or ``None``.
        """
        with self._sessions.transaction() as db:
            row = db.scalars(
                select(UserSessionRow).where(UserSessionRow.token_hash == token_hash)
            ).first()
            if row is None:
                return None
            return UserSession(
                id=row.id,
                user_id=row.user_id,
                org_id=row.org_id,
                created_at=_as_utc(row.created_at),
                expires_at=_as_utc(row.expires_at),
                revoked_at=_as_utc(row.revoked_at) if row.revoked_at else None,
            )

    def revoke(self, org_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Revoke one session of ``org_id`` (no-op if already revoked).

        Args:
            org_id: Owning organization (enforced).
            session_id: Session to revoke.
        """
        with self._sessions.transaction() as db:
            db.execute(
                update(UserSessionRow)
                .where(
                    UserSessionRow.id == session_id,
                    UserSessionRow.org_id == org_id,
                    UserSessionRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )

    def revoke_all_for_user(
        self, org_id: uuid.UUID, user_id: uuid.UUID, except_session_id: uuid.UUID | None = None
    ) -> int:
        """Revoke every active session of a user.

        Args:
            org_id: Owning organization (enforced).
            user_id: User whose sessions to revoke.
            except_session_id: A session to keep.

        Returns:
            Number of sessions revoked.
        """
        statement = (
            update(UserSessionRow)
            .where(
                UserSessionRow.org_id == org_id,
                UserSessionRow.user_id == user_id,
                UserSessionRow.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        if except_session_id is not None:
            statement = statement.where(UserSessionRow.id != except_session_id)
        with self._sessions.transaction() as db:
            return _rowcount(db.execute(statement))

    def delete_expired(self, before: datetime) -> int:
        """Delete sessions that expired before ``before``, across all orgs.

        Args:
            before: Cut-off time.

        Returns:
            Number of sessions deleted.
        """
        with self._sessions.transaction() as db:
            return _rowcount(
                db.execute(delete(UserSessionRow).where(UserSessionRow.expires_at < before))
            )


class SqlInvitationRepository:
    """Stores invitations by token digest."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, invitation: Invitation, token_hash: str) -> Invitation:
        """Store a new invitation.

        Args:
            invitation: The invitation metadata.
            token_hash: SHA-256 hex digest of the invitation token.

        Returns:
            The stored invitation.
        """
        with self._sessions.transaction() as db:
            db.add(
                InvitationRow(
                    id=invitation.id,
                    org_id=invitation.org_id,
                    email=invitation.email,
                    role=invitation.role.value,
                    purpose=invitation.purpose.value,
                    token_hash=token_hash,
                    created_by=invitation.created_by,
                    created_at=invitation.created_at,
                    expires_at=invitation.expires_at,
                )
            )
        return invitation

    def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        """Look up an invitation by its token digest.

        Args:
            token_hash: SHA-256 hex digest of the presented token.

        Returns:
            The invitation, or ``None``.
        """
        with self._sessions.transaction() as db:
            row = db.scalars(
                select(InvitationRow).where(InvitationRow.token_hash == token_hash)
            ).first()
            return _invitation_from_row(row) if row else None

    def list_pending(
        self, org_id: uuid.UUID, purpose: InvitationPurpose, now: datetime
    ) -> list[Invitation]:
        """List an organization's unredeemed, unrevoked, unexpired tokens, newest first.

        Args:
            org_id: Organization (enforced).
            purpose: Which kind of token to list.
            now: Current time.

        Returns:
            The pending tokens.
        """
        with self._sessions.transaction() as db:
            rows = db.scalars(
                select(InvitationRow)
                .where(
                    InvitationRow.org_id == org_id,
                    InvitationRow.purpose == purpose.value,
                    InvitationRow.accepted_at.is_(None),
                    InvitationRow.revoked_at.is_(None),
                    InvitationRow.expires_at > now,
                )
                .order_by(InvitationRow.created_at.desc())
            )
            return [_invitation_from_row(row) for row in rows]

    def revoke(self, org_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        """Revoke a pending token.

        Args:
            org_id: Owning organization (enforced).
            invitation_id: Token to revoke.

        Raises:
            NotFoundError: If no unredeemed, unrevoked token has this id in this org.
        """
        with self._sessions.transaction() as db:
            revoked = db.execute(
                update(InvitationRow)
                .where(
                    InvitationRow.id == invitation_id,
                    InvitationRow.org_id == org_id,
                    InvitationRow.accepted_at.is_(None),
                    InvitationRow.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            if _rowcount(revoked) != 1:
                raise NotFoundError(
                    f"pending invitation {invitation_id} not found for org {org_id}"
                )

    def redeem_password_reset(self, invitation: Invitation, password_hash: str) -> User:
        """Redeem a password-reset token, in one transaction.

        Args:
            invitation: The reset token being redeemed.
            password_hash: Argon2 hash of the new password.

        Returns:
            The user whose password was reset.

        Raises:
            InvitationInvalidError: If the token was already used or revoked,
                or its account no longer exists.
        """
        with self._sessions.transaction() as db:
            _claim(db, invitation)
            row = db.scalars(
                select(UserRow).where(
                    UserRow.org_id == invitation.org_id, UserRow.email == invitation.email
                )
            ).first()
            if row is None:
                raise InvitationInvalidError(_TOKEN_UNUSABLE)
            row.password_hash = password_hash
            row.password_changed_at = datetime.now(UTC)
            row.failed_login_count = 0
            row.locked_until = None
            db.execute(delete(UserSessionRow).where(UserSessionRow.user_id == row.id))
            return _credentials_from_row(row).user

    def accept(self, invitation: Invitation, user: User, password_hash: str) -> User:
        """Mark an invitation used and create its user, in one transaction.

        Args:
            invitation: The invitation being redeemed.
            user: The user to create.
            password_hash: Argon2 hash of the chosen password.

        Returns:
            The created user.

        Raises:
            InvitationInvalidError: If the invitation was already accepted or revoked.
            ConflictError: If an account with this email already exists.
        """
        with self._sessions.transaction() as db:
            _claim(db, invitation)
            _insert_user(db, user, password_hash)
        return user


_TOKEN_UNUSABLE = "invitation is invalid, expired or already used"


def _claim(db: Session, invitation: Invitation) -> None:
    """Mark a token used, atomically; raise if it was already used or revoked.

    The conditional UPDATE is the check: of two concurrent redemptions of
    one token, only one matches a row, so a token can never be used twice.
    """
    claimed = db.execute(
        update(InvitationRow)
        .where(
            InvitationRow.id == invitation.id,
            InvitationRow.org_id == invitation.org_id,
            InvitationRow.accepted_at.is_(None),
            InvitationRow.revoked_at.is_(None),
        )
        .values(accepted_at=datetime.now(UTC))
    )
    if _rowcount(claimed) != 1:
        raise InvitationInvalidError(_TOKEN_UNUSABLE)


def _invitation_from_row(row: InvitationRow) -> Invitation:
    """Convert an invitation row to its contract."""
    return Invitation(
        id=row.id,
        org_id=row.org_id,
        email=row.email,
        role=Role(row.role),
        purpose=InvitationPurpose(row.purpose),
        created_by=row.created_by,
        created_at=_as_utc(row.created_at),
        expires_at=_as_utc(row.expires_at),
        accepted_at=_as_utc(row.accepted_at) if row.accepted_at else None,
        revoked_at=_as_utc(row.revoked_at) if row.revoked_at else None,
    )


def _rowcount(result: Result[Any]) -> int:
    """Rows affected by an UPDATE/DELETE (DML statements return a ``CursorResult``)."""
    return cast(CursorResult[Any], result).rowcount


class SqlUploadRepository:
    """Stores uploaded files, scoped by organization."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, upload: Upload, data: bytes) -> Upload:
        """Store an uploaded file.

        Args:
            upload: Its metadata.
            data: Its content.

        Returns:
            The stored metadata.
        """
        with self._sessions.transaction() as db:
            db.add(
                UploadRow(
                    id=upload.id,
                    org_id=upload.org_id,
                    filename=upload.filename,
                    format=upload.format.value,
                    size_bytes=upload.size_bytes,
                    sha256=upload.sha256,
                    data=data,
                    created_at=upload.created_at,
                )
            )
        return upload

    def get(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> Upload:
        """Fetch an upload's metadata (without loading its content).

        Args:
            org_id: Owning organization (enforced).
            upload_id: Upload identifier.

        Returns:
            The metadata.

        Raises:
            NotFoundError: If the upload does not exist in this org.
        """
        columns = (
            UploadRow.id,
            UploadRow.org_id,
            UploadRow.filename,
            UploadRow.format,
            UploadRow.size_bytes,
            UploadRow.sha256,
            UploadRow.created_at,
        )
        # Explicit columns so the file content (up to upload_max_bytes) is
        # not loaded just to read its metadata.
        with self._sessions.transaction() as db:
            row = db.execute(
                select(*columns).where(UploadRow.id == upload_id, UploadRow.org_id == org_id)
            ).first()
            if row is None:
                raise NotFoundError(f"upload {upload_id} not found for org {org_id}")
            return Upload(
                id=row.id,
                org_id=row.org_id,
                filename=row.filename,
                format=UploadFormat(row.format),
                size_bytes=row.size_bytes,
                sha256=row.sha256,
                created_at=_as_utc(row.created_at),
            )

    def get_data(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> bytes:
        """Fetch an upload's content.

        Args:
            org_id: Owning organization (enforced).
            upload_id: Upload identifier.

        Returns:
            The file content.

        Raises:
            NotFoundError: If the upload does not exist in this org.
        """
        with self._sessions.transaction() as db:
            data = db.scalars(
                select(UploadRow.data).where(UploadRow.id == upload_id, UploadRow.org_id == org_id)
            ).first()
            if data is None:
                raise NotFoundError(f"upload {upload_id} not found for org {org_id}")
            return bytes(data)


class SqlMappingTemplateRepository:
    """Stores saved column mappings, scoped by organization."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, template: MappingTemplate) -> MappingTemplate:
        """Store a template, replacing any of the org's templates with the same name.

        Args:
            template: The template.

        Returns:
            The stored template.
        """
        # Delete-then-insert in one transaction: saving under an existing name
        # replaces that template (names are unique per org).
        with self._sessions.transaction() as db:
            db.execute(
                delete(MappingTemplateRow).where(
                    MappingTemplateRow.org_id == template.org_id,
                    MappingTemplateRow.name == template.name,
                )
            )
            db.add(
                MappingTemplateRow(
                    id=template.id,
                    org_id=template.org_id,
                    name=template.name,
                    mapping={column: role.value for column, role in template.mapping.items()},
                    created_at=template.created_at,
                )
            )
        return template

    def list_templates(self, org_id: uuid.UUID) -> list[MappingTemplate]:
        """List an organization's templates, by name.

        Args:
            org_id: Organization (enforced).

        Returns:
            The templates.
        """
        with self._sessions.transaction() as db:
            rows = db.scalars(
                select(MappingTemplateRow)
                .where(MappingTemplateRow.org_id == org_id)
                .order_by(MappingTemplateRow.name)
            )
            return [
                MappingTemplate(
                    id=row.id,
                    org_id=row.org_id,
                    name=row.name,
                    mapping={column: ColumnRole(role) for column, role in row.mapping.items()},
                    created_at=_as_utc(row.created_at),
                )
                for row in rows
            ]

    def delete(self, org_id: uuid.UUID, template_id: uuid.UUID) -> None:
        """Delete a template.

        Args:
            org_id: Owning organization (enforced).
            template_id: Template identifier.

        Raises:
            NotFoundError: If the template does not exist in this org.
        """
        with self._sessions.transaction() as db:
            deleted = db.execute(
                delete(MappingTemplateRow).where(
                    MappingTemplateRow.id == template_id, MappingTemplateRow.org_id == org_id
                )
            )
            if _rowcount(deleted) != 1:
                raise NotFoundError(f"mapping template {template_id} not found for org {org_id}")


class SqlRunRepository:
    """Stores :class:`PipelineRun` metadata and serves as the run queue.

    Organization-facing methods are scoped by ``org_id``. The queue methods
    (``claim_next``, ``fail_exhausted``, ``renew_lease``, ``release``) serve
    the run worker, which executes every organization's runs, each under the
    ``org_id`` the claimed run carries.
    """

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, run: PipelineRun) -> PipelineRun:
        """Insert a new run.

        Args:
            run: The run to store.

        Returns:
            The stored run.
        """
        with self._sessions.transaction() as session:
            session.add(
                RunRow(
                    id=run.id,
                    org_id=run.org_id,
                    source=run.spec.source.value,
                    status=run.status.value,
                    stage=run.stage.value,
                    progress=run.progress.model_dump(),
                    attempts=run.attempts,
                    cancel_requested=run.cancel_requested,
                    dataset_id=run.dataset_id,
                    request_payload=run.spec.model_dump(mode="json"),
                    error=run.error,
                    created_at=run.created_at,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
            )
        return run

    def update(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        """Update an existing run's outcome.

        Writes ``status``, ``stage``, ``progress``, ``dataset_id``, ``error``
        and ``finished_at``; a finished run also gives up its lease.

        Args:
            org_id: Owning organization (enforced).
            run: The run with new field values.

        Returns:
            The stored run.

        Raises:
            NotFoundError: If the run does not exist for this org.
        """
        with self._sessions.transaction() as session:
            row = self._row(session, org_id, run.id)
            row.status = run.status.value
            row.stage = run.stage.value
            row.progress = run.progress.model_dump()
            row.dataset_id = run.dataset_id
            row.error = run.error
            row.finished_at = run.finished_at
            if run.status in FINISHED_STATUSES:
                row.worker_id = None
                row.lease_expires_at = None
            return _run_from_row(row)

    def get(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        """Fetch a run by id, scoped to an organization.

        Args:
            org_id: Owning organization (enforced).
            run_id: Run identifier.

        Returns:
            The run.

        Raises:
            NotFoundError: If the run does not exist for this org.
        """
        with self._sessions.transaction() as session:
            return _run_from_row(self._row(session, org_id, run_id))

    def list_for_org(self, org_id: uuid.UUID) -> list[PipelineRun]:
        """List runs for an organization, newest first.

        Args:
            org_id: Owning organization.

        Returns:
            The runs.
        """
        with self._sessions.transaction() as session:
            rows = session.scalars(
                select(RunRow).where(RunRow.org_id == org_id).order_by(RunRow.created_at.desc())
            )
            return [_run_from_row(r) for r in rows]

    def request_cancel(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        """Cancel a run: a pending one at once, a running one at its next checkpoint.

        Args:
            org_id: Owning organization (enforced).
            run_id: Run to cancel.

        Returns:
            The run after the request; a finished run is returned unchanged.

        Raises:
            NotFoundError: If the run does not exist for this org.
        """
        with self._sessions.transaction() as session:
            row = self._row(session, org_id, run_id)
            if row.status == RunStatus.PENDING.value:
                row.status = RunStatus.CANCELLED.value
                row.cancel_requested = True
                row.finished_at = utcnow()
            elif row.status == RunStatus.RUNNING.value:
                row.cancel_requested = True
            return _run_from_row(row)

    def claim(
        self, org_id: uuid.UUID, run_id: uuid.UUID, worker_id: str, lease_seconds: float
    ) -> PipelineRun | None:
        """Atomically claim one pending run for ``worker_id``.

        Args:
            org_id: Owning organization (enforced).
            run_id: The run.
            worker_id: The claiming worker.
            lease_seconds: How long the claim lasts unless renewed.

        Returns:
            The claimed run, or ``None`` if it is no longer pending.
        """
        now = utcnow()
        with self._sessions.transaction() as session:
            claimed = session.execute(
                update(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.org_id == org_id,
                    RunRow.status == RunStatus.PENDING.value,
                )
                .values(
                    status=RunStatus.RUNNING.value,
                    attempts=RunRow.attempts + 1,
                    worker_id=worker_id,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    started_at=func.coalesce(RunRow.started_at, now),
                )
                .execution_options(synchronize_session=False)
            )
            if _rowcount(claimed) != 1:
                return None
            return _run_from_row(self._row(session, org_id, run_id))

    def claim_next(
        self, worker_id: str, lease_seconds: float, max_lost_leases: int
    ) -> PipelineRun | None:
        """Atomically claim the next runnable run for ``worker_id``.

        Among runnable runs, the one whose organization has the fewest runs
        executing right now goes first, oldest first on a tie.

        Args:
            worker_id: The claiming worker.
            lease_seconds: How long the claim lasts unless renewed.
            max_lost_leases: Unexpected worker stops after which a run is
                failed rather than claimed again.

        Returns:
            The claimed run, or ``None`` if nothing is runnable.
        """
        while True:
            now = utcnow()
            with self._sessions.transaction() as session:
                # Fair share: plain FIFO would let one organization's backlog
                # of 100 runs hold every other organization's runs behind it.
                # Ordering by how many runs the candidate's organization is
                # executing now (live leases only) interleaves organizations,
                # and created_at keeps each organization first-in, first-out.
                executing = aliased(RunRow)
                org_load = (
                    select(func.count())
                    .select_from(executing)
                    .where(
                        executing.org_id == RunRow.org_id,
                        executing.status == RunStatus.RUNNING.value,
                        executing.lease_expires_at >= now,
                    )
                    .scalar_subquery()
                )
                # SKIP LOCKED: concurrent workers on PostgreSQL skip a row
                # another worker is claiming instead of queueing behind it.
                # (SQLite ignores FOR UPDATE; its writers are serialized.)
                candidate = session.execute(
                    select(RunRow.id, RunRow.status, RunRow.attempts, RunRow.lost_leases)
                    .where(_runnable(now, max_lost_leases))
                    .order_by(org_load, RunRow.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).first()
                if candidate is None:
                    return None
                resumed_after_crash = candidate.status == RunStatus.RUNNING.value
                # The claim is conditional on the state that was read (and on
                # the run still being runnable), so it is atomic on any
                # database even without row locks: of two workers that read
                # the same candidate, only one update matches.
                claimed = session.execute(
                    update(RunRow)
                    .where(
                        RunRow.id == candidate.id,
                        RunRow.status == candidate.status,
                        RunRow.attempts == candidate.attempts,
                        RunRow.lost_leases == candidate.lost_leases,
                        _runnable(now, max_lost_leases),
                    )
                    .values(
                        status=RunStatus.RUNNING.value,
                        attempts=candidate.attempts + 1,
                        # Its previous worker's lease ran out: that worker
                        # stopped without handing the run back.
                        lost_leases=candidate.lost_leases + (1 if resumed_after_crash else 0),
                        worker_id=worker_id,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        started_at=func.coalesce(RunRow.started_at, now),
                    )
                    .execution_options(synchronize_session=False)
                )
                if _rowcount(claimed) == 1:
                    row = session.get(RunRow, candidate.id, populate_existing=True)
                    assert row is not None
                    return _run_from_row(row)
            # Another worker claimed it between our read and update; try the next.

    def fail_exhausted(self, max_lost_leases: int) -> list[PipelineRun]:
        """Fail runs whose worker has now stopped unexpectedly ``max_lost_leases`` times.

        Args:
            max_lost_leases: Which unexpected worker stop fails a run (3: the third).

        Returns:
            The runs marked failed.
        """
        now = utcnow()
        with self._sessions.transaction() as session:
            rows = list(
                session.scalars(
                    select(RunRow)
                    .where(_lease_expired(now), RunRow.lost_leases + 1 >= max_lost_leases)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                # This expiry is itself a lost lease: count it, so the stored
                # counter and the message agree.
                row.lost_leases += 1
                row.status = RunStatus.FAILED.value
                row.error = (
                    f"the run's worker stopped unexpectedly {row.lost_leases} times; start it again"
                )
                row.finished_at = now
                row.worker_id = None
                row.lease_expires_at = None
                # A failed run keeps no output; its crashed attempt may have
                # stored part of a dataset that no retry will now replace.
                _delete_run_output(session, row.org_id, row.id)
            return [_run_from_row(r) for r in rows]

    def renew_lease(self, run_id: uuid.UUID, worker_id: str, lease_seconds: float) -> bool:
        """Extend a running run's lease, if ``worker_id`` still holds it.

        Args:
            run_id: The run.
            worker_id: The worker executing it.
            lease_seconds: New lease length from now.

        Returns:
            Whether the lease was renewed.
        """
        with self._sessions.transaction() as session:
            result = session.execute(
                update(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.worker_id == worker_id,
                    RunRow.status == RunStatus.RUNNING.value,
                )
                .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
                .execution_options(synchronize_session=False)
            )
            return _rowcount(result) == 1

    def release(self, run_id: uuid.UUID, worker_id: str) -> None:
        """Hand an unfinished run back to the queue after a clean stop.

        Args:
            run_id: The run.
            worker_id: The worker that held it.
        """
        # Back to pending rather than an expired lease: the next poll claims
        # it as an ordinary pending run, and a planned restart (deploy) is not
        # counted as a lost lease. Stage, progress and attempts are kept so
        # the run's history stays visible while it waits.
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.worker_id == worker_id,
                    RunRow.status == RunStatus.RUNNING.value,
                )
                .with_for_update()
            ).first()
            if row is None:  # finished, deleted, or taken over by another worker
                return
            # A cancellation requested before the stop is honoured here: the
            # user asked for the run to end, so it must not start over.
            if row.cancel_requested:
                row.status = RunStatus.CANCELLED.value
                row.finished_at = utcnow()
            else:
                row.status = RunStatus.PENDING.value
            row.worker_id = None
            row.lease_expires_at = None
            # A pending run holds no output: the stopped attempt's partial
            # dataset goes now (the next attempt would delete it anyway), so
            # cancelling the run while it waits leaves nothing behind.
            _delete_run_output(session, row.org_id, row.id)

    @staticmethod
    def _row(session: Session, org_id: uuid.UUID, run_id: uuid.UUID) -> RunRow:
        """The run's row, scoped to its organization."""
        row = session.scalars(
            select(RunRow).where(RunRow.id == run_id, RunRow.org_id == org_id)
        ).first()
        if row is None:
            raise NotFoundError(f"run {run_id} not found for org {org_id}")
        return row


def _lease_expired(now: datetime) -> ColumnElement[bool]:
    """Running runs whose worker stopped renewing the lease (crashed, killed, hung)."""
    return and_(RunRow.status == RunStatus.RUNNING.value, RunRow.lease_expires_at < now)


def _runnable(now: datetime, max_lost_leases: int) -> ColumnElement[bool]:
    """Runs a worker may claim: pending, or an expired lease short of the limit."""
    return or_(
        RunRow.status == RunStatus.PENDING.value,
        and_(_lease_expired(now), RunRow.lost_leases + 1 < max_lost_leases),
    )


def _run_from_row(row: RunRow) -> PipelineRun:
    """Convert a run row to its contract."""
    return PipelineRun(
        id=row.id,
        org_id=row.org_id,
        spec=SourceSpec.model_validate(row.request_payload),
        status=RunStatus(row.status),
        stage=RunStage(row.stage),
        progress=RunProgress.model_validate(row.progress or {}),
        attempts=row.attempts,
        cancel_requested=row.cancel_requested,
        dataset_id=row.dataset_id,
        error=row.error,
        created_at=_as_utc(row.created_at),
        started_at=_as_utc(row.started_at) if row.started_at else None,
        finished_at=_as_utc(row.finished_at) if row.finished_at else None,
    )


class SqlDatasetRepository:
    """Stores normalized datasets and their records, scoped by organization."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        """Store a dataset and its records atomically.

        Args:
            dataset: Dataset metadata.
            records: Normalized records, in export order.

        Returns:
            The stored dataset.

        Raises:
            StorageError: If a record has no ``record_key``, or two records
                share a compound and measurement context within the dataset.
        """
        with self._sessions.transaction() as session:
            session.add(
                DatasetRow(
                    id=dataset.id,
                    org_id=dataset.org_id,
                    run_id=dataset.run_id,
                    name=dataset.name,
                    source=dataset.source.value,
                    record_count=dataset.record_count,
                    created_at=dataset.created_at,
                )
            )
            # The dataset row goes first so its records' foreign key has a
            # parent. Raising below rolls back the dataset too: a dataset is
            # stored whole or not at all.
            session.flush()
            for record in records:
                if record.record_key is None:
                    raise StorageError(f"record {record.source_record_id!r} has no record_key")
                session.add(_record_to_row(dataset.org_id, dataset.id, record))
        return dataset

    def get(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetWithRecords:
        """Fetch a dataset with its records, scoped to an organization.

        Args:
            org_id: Owning organization (enforced).
            dataset_id: Dataset identifier.

        Returns:
            The dataset and its records.

        Raises:
            NotFoundError: If the dataset does not exist for this org.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(DatasetRow).where(DatasetRow.id == dataset_id, DatasetRow.org_id == org_id)
            ).first()
            if row is None:
                raise NotFoundError(f"dataset {dataset_id} not found for org {org_id}")
            record_rows = session.scalars(
                select(NormalizedRecordRow).where(NormalizedRecordRow.dataset_id == dataset_id)
            )
            return DatasetWithRecords(
                dataset=_dataset_from_row(row),
                records=[_record_from_row(r) for r in record_rows],
            )

    def list_for_org(self, org_id: uuid.UUID) -> list[Dataset]:
        """List datasets for an organization, newest first.

        Args:
            org_id: Owning organization.

        Returns:
            Dataset metadata.
        """
        with self._sessions.transaction() as session:
            rows = session.scalars(
                select(DatasetRow)
                .where(DatasetRow.org_id == org_id)
                .order_by(DatasetRow.created_at.desc())
            )
            return [_dataset_from_row(r) for r in rows]

    def filter_records(
        self, org_id: uuid.UUID, dataset_id: uuid.UUID, filters: DatasetFilter
    ) -> list[NormalizedRecord]:
        """Query a dataset's records with filters.

        Args:
            org_id: Owning organization (enforced).
            dataset_id: Dataset identifier.
            filters: Filter criteria.

        Returns:
            Matching records.
        """
        from dndlabs.filtering.query import build_predicate

        stmt = select(NormalizedRecordRow).where(
            NormalizedRecordRow.org_id == org_id, NormalizedRecordRow.dataset_id == dataset_id
        )
        stmt = build_predicate(stmt, NormalizedRecordRow, filters)
        stmt = stmt.limit(filters.limit).offset(filters.offset)
        with self._sessions.transaction() as session:
            return [_record_from_row(r) for r in session.scalars(stmt)]

    def delete_org_data(self, org_id: uuid.UUID) -> int:
        """Delete an organization's data (privacy).

        Removes its runs, uploads, datasets and everything derived from them.
        The organization, its API keys, users, sessions, invitations and
        mapping templates are kept, so the caller is not locked out.

        Args:
            org_id: Organization whose data is being deleted.

        Returns:
            Number of datasets deleted.
        """
        with self._sessions.transaction() as session:
            dataset_ids = list(
                session.scalars(select(DatasetRow.id).where(DatasetRow.org_id == org_id))
            )
            # Children before parents, so every foreign key is satisfied at
            # each step without relying on ON DELETE CASCADE.
            session.execute(delete(EnrichmentResultRow).where(EnrichmentResultRow.org_id == org_id))
            session.execute(delete(FeatureVectorRow).where(FeatureVectorRow.org_id == org_id))
            session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.org_id == org_id))
            session.execute(delete(QualityReportRow).where(QualityReportRow.org_id == org_id))
            session.execute(delete(NormalizedRecordRow).where(NormalizedRecordRow.org_id == org_id))
            session.execute(delete(DatasetRow).where(DatasetRow.org_id == org_id))
            session.execute(delete(RunRow).where(RunRow.org_id == org_id))
            session.execute(delete(UploadRow).where(UploadRow.org_id == org_id))
            return len(dataset_ids)

    def delete_for_run(self, org_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        """Delete the dataset a run produced, with everything that references it.

        Args:
            org_id: Owning organization (enforced).
            run_id: The run.

        Returns:
            Whether a dataset was deleted.
        """
        with self._sessions.transaction() as session:
            return _delete_run_output(session, org_id, run_id)


def _delete_run_output(session: Session, org_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Delete the dataset ``run_id`` produced and everything referencing it, if any."""
    dataset_id = session.scalars(
        select(DatasetRow.id).where(DatasetRow.org_id == org_id, DatasetRow.run_id == run_id)
    ).first()
    if dataset_id is None:
        return False
    record_ids = select(NormalizedRecordRow.id).where(NormalizedRecordRow.dataset_id == dataset_id)
    session.execute(
        delete(EnrichmentResultRow).where(EnrichmentResultRow.record_id.in_(record_ids))
    )
    session.execute(delete(FeatureVectorRow).where(FeatureVectorRow.record_id.in_(record_ids)))
    session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.dataset_id == dataset_id))
    session.execute(delete(QualityReportRow).where(QualityReportRow.dataset_id == dataset_id))
    session.execute(delete(NormalizedRecordRow).where(NormalizedRecordRow.dataset_id == dataset_id))
    session.execute(delete(DatasetRow).where(DatasetRow.id == dataset_id))
    return True


def _record_to_row(
    org_id: uuid.UUID, dataset_id: uuid.UUID, record: NormalizedRecord
) -> NormalizedRecordRow:
    """Convert a normalized record to a row."""
    return NormalizedRecordRow(
        id=record.id,
        org_id=org_id,
        dataset_id=dataset_id,
        record_key=record.record_key,
        source=record.source.value,
        source_record_id=record.source_record_id,
        name=record.name,
        canonical_smiles=record.canonical_smiles,
        inchi=record.inchi,
        inchikey=record.inchikey,
        molecular_formula=record.molecular_formula,
        molecular_weight=record.molecular_weight,
        target=record.target,
        assay_type=record.assay_type,
        assay_format=record.assay_format.value if record.assay_format else None,
        control=record.control.value if record.control else None,
        context_key=record.context_key(),
        activity_value_nm=record.activity_value_nm,
        activity_relation=record.activity_relation,
    )


def _record_from_row(row: NormalizedRecordRow) -> NormalizedRecord:
    """Convert a row to a normalized record."""
    return NormalizedRecord(
        id=row.id,
        dataset_id=row.dataset_id,
        record_key=row.record_key,
        source=SourceType(row.source),
        source_record_id=row.source_record_id,
        name=row.name,
        canonical_smiles=row.canonical_smiles,
        inchi=row.inchi,
        inchikey=row.inchikey,
        molecular_formula=row.molecular_formula,
        molecular_weight=row.molecular_weight,
        target=row.target,
        assay_type=row.assay_type,
        assay_format=AssayFormat(row.assay_format) if row.assay_format else None,
        control=ControlType(row.control) if row.control else None,
        activity_value_nm=row.activity_value_nm,
        activity_relation=row.activity_relation,
    )


def _dataset_from_row(row: DatasetRow) -> Dataset:
    """Convert a dataset row to its contract."""
    return Dataset(
        id=row.id,
        org_id=row.org_id,
        run_id=row.run_id,
        name=row.name,
        source=SourceType(row.source),
        record_count=row.record_count,
        created_at=_as_utc(row.created_at),
    )


class SqlQualityReportRepository:
    """Stores per-run quality reports, scoped by organization."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def save(self, org_id: uuid.UUID, report: QualityReport) -> QualityReport:
        """Store a quality report.

        Args:
            org_id: Owning organization.
            report: The report; ``dataset_id`` must be set.

        Returns:
            The stored report.

        Raises:
            StorageError: If ``dataset_id`` is missing.
        """
        if report.dataset_id is None:
            raise StorageError("quality report must reference a dataset")
        with self._sessions.transaction() as session:
            session.add(
                QualityReportRow(
                    org_id=org_id,
                    run_id=report.run_id,
                    dataset_id=report.dataset_id,
                    total_records=report.total_records,
                    accepted_records=report.accepted_records,
                    rejected_records=report.rejected_records,
                    duplicate_records=report.duplicate_records,
                    pass_rate=report.pass_rate,
                    report=report.model_dump(mode="json"),
                    created_at=report.created_at,
                )
            )
            # Each issue is also written as its own row; reads come from the
            # report JSON above.
            for issue in report.issues:
                session.add(
                    ValidationIssueRow(
                        org_id=org_id,
                        dataset_id=report.dataset_id,
                        source_record_id=issue.source_record_id,
                        severity=issue.severity.value,
                        rule=issue.rule,
                        field=issue.field,
                        message=issue.message,
                    )
                )
        return report

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> QualityReport:
        """Fetch the quality report of a dataset.

        Args:
            org_id: Owning organization (enforced).
            dataset_id: Dataset identifier.

        Returns:
            The report.

        Raises:
            NotFoundError: If no report exists for this org/dataset.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(QualityReportRow).where(
                    QualityReportRow.dataset_id == dataset_id, QualityReportRow.org_id == org_id
                )
            ).first()
            if row is None:
                raise NotFoundError(f"quality report for dataset {dataset_id} not found")
            return QualityReport.model_validate(row.report)


class SqlFeatureRepository:
    """Stores computed feature vectors."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def save_many(self, org_id: uuid.UUID, vectors: Sequence[FeatureVector]) -> int:
        """Store feature vectors, all in one transaction.

        The records they reference must already be stored (foreign key); the
        orchestrator saves the dataset first.

        Args:
            org_id: Owning organization.
            vectors: Vectors to store.

        Returns:
            Number stored.
        """
        with self._sessions.transaction() as session:
            session.add_all(
                FeatureVectorRow(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    record_id=v.record_id,
                    descriptors=v.descriptors,
                    alerts=[a.model_dump(mode="json") for a in v.alerts],
                    fingerprint_bits=v.fingerprint_bits,
                    fingerprint_radius=v.fingerprint_radius,
                    fingerprint_n_bits=v.fingerprint_n_bits,
                    created_at=datetime.now(UTC),
                )
                for v in vectors
            )
        return len(vectors)

    def features_for(
        self, org_id: uuid.UUID, record_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, StoredFeatures]:
        """Return the stored descriptors and alerts of the given records.

        Args:
            org_id: Owning organization.
            record_ids: The records.

        Returns:
            Stored features by record id, for the records that have a vector;
            ``alerts`` is ``None`` for vectors stored before alerts existed.
        """
        found: dict[uuid.UUID, StoredFeatures] = {}
        ids = list(record_ids)
        columns = (
            FeatureVectorRow.record_id,
            FeatureVectorRow.descriptors,
            FeatureVectorRow.alerts,
        )
        with self._sessions.transaction() as session:
            for start in range(0, len(ids), _IN_CHUNK):
                rows = session.execute(
                    select(*columns).where(
                        FeatureVectorRow.org_id == org_id,
                        FeatureVectorRow.record_id.in_(ids[start : start + _IN_CHUNK]),
                    )
                )
                for record_id, descriptors, alerts in rows:
                    found[record_id] = StoredFeatures.model_validate(
                        {"record_id": record_id, "descriptors": descriptors, "alerts": alerts}
                    )
        return found


class SqlEnrichmentRepository:
    """Stores enrichment results."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def save_many(self, org_id: uuid.UUID, results: Sequence[EnrichmentResult]) -> int:
        """Store enrichment results, all in one transaction.

        The records they reference must already be stored (foreign key).

        Args:
            org_id: Owning organization.
            results: Results to store.

        Returns:
            Number stored.
        """
        with self._sessions.transaction() as session:
            session.add_all(
                EnrichmentResultRow(
                    id=uuid.uuid4(),
                    org_id=org_id,
                    record_id=r.record_id,
                    status=r.status,
                    model_id=r.model_id,
                    candidates=(
                        [c.model_dump(mode="json") for c in r.candidates] if r.candidates else None
                    ),
                    error=r.error,
                    created_at=r.created_at,
                )
                for r in results
            )
        return len(results)

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> list[EnrichmentResult]:
        """Fetch enrichment results for every record in a dataset.

        Args:
            org_id: Owning organization (enforced).
            dataset_id: Dataset identifier.

        Returns:
            The enrichment results (may be empty if none were computed yet).
        """
        from dndlabs.core.schemas import GeneratedCandidate

        with self._sessions.transaction() as session:
            record_ids = list(
                session.scalars(
                    select(NormalizedRecordRow.id).where(
                        NormalizedRecordRow.org_id == org_id,
                        NormalizedRecordRow.dataset_id == dataset_id,
                    )
                )
            )
            if not record_ids:
                return []
            rows = session.scalars(
                select(EnrichmentResultRow).where(
                    EnrichmentResultRow.org_id == org_id,
                    EnrichmentResultRow.record_id.in_(record_ids),
                )
            )
            return [
                EnrichmentResult(
                    record_id=row.record_id,
                    status=row.status,
                    model_id=row.model_id,
                    candidates=(
                        [GeneratedCandidate.model_validate(c) for c in row.candidates]
                        if row.candidates
                        else None
                    ),
                    error=row.error,
                    created_at=_as_utc(row.created_at),
                )
                for row in rows
            ]


def build_sql_repositories(engine: object, expected_revision: str | None = None) -> Repositories:
    """Build the full repository bundle on one engine.

    Args:
        engine: Engine to bind to.
        expected_revision: Migration revision the readiness check requires;
            ``None`` when the schema is not managed by migrations.

    Returns:
        SQL-backed repositories.
    """
    sessions = SessionFactory(engine)  # type: ignore[arg-type]
    return Repositories(
        organizations=SqlOrganizationRepository(sessions, expected_revision),
        api_keys=SqlApiKeyRepository(sessions),
        users=SqlUserRepository(sessions),
        sessions=SqlSessionRepository(sessions),
        invitations=SqlInvitationRepository(sessions),
        uploads=SqlUploadRepository(sessions),
        mapping_templates=SqlMappingTemplateRepository(sessions),
        runs=SqlRunRepository(sessions),
        datasets=SqlDatasetRepository(sessions),
        reports=SqlQualityReportRepository(sessions),
        features=SqlFeatureRepository(sessions),
        enrichments=SqlEnrichmentRepository(sessions),
    )
