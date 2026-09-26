"""SQLAlchemy implementations of the ``core.protocols`` repositories.

Every method that reads or writes a specific entity takes ``org_id`` and
filters by it — this is the tenant-isolation boundary. No method accepts a
caller-supplied override; ``org_id`` always comes from the authenticated
request context, never from a request body or query string.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dndlabs.core.exceptions import (
    ConflictError,
    InvitationInvalidError,
    NotFoundError,
    StorageError,
)
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    ApiKeyRecord,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentResult,
    FeatureVector,
    Invitation,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    Role,
    RunStatus,
    SourceSpec,
    SourceType,
    User,
    UserCredentials,
    UserSession,
)
from dndlabs.storage.database import SessionFactory
from dndlabs.storage.models import (
    ApiKeyRow,
    DatasetRow,
    EnrichmentResultRow,
    FeatureVectorRow,
    InvitationRow,
    NormalizedRecordRow,
    OrganizationRow,
    QualityReportRow,
    RunRow,
    UserRow,
    UserSessionRow,
    ValidationIssueRow,
)


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to naive datetimes returned by SQLite."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class SqlOrganizationRepository:
    """Stores organizations."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

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
            StorageError: If the database is unreachable, or the
                ``organizations`` table is missing (schema not migrated).
        """
        with self._sessions.transaction() as session:
            session.execute(select(OrganizationRow.id).limit(1))


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
        """Delete sessions that expired before ``before``.

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
            if row is None:
                return None
            return Invitation(
                id=row.id,
                org_id=row.org_id,
                email=row.email,
                role=Role(row.role),
                created_by=row.created_by,
                created_at=_as_utc(row.created_at),
                expires_at=_as_utc(row.expires_at),
                accepted_at=_as_utc(row.accepted_at) if row.accepted_at else None,
            )

    def accept(self, invitation: Invitation, user: User, password_hash: str) -> User:
        """Mark an invitation used and create its user, in one transaction.

        Args:
            invitation: The invitation being redeemed.
            user: The user to create.
            password_hash: Argon2 hash of the chosen password.

        Returns:
            The created user.

        Raises:
            InvitationInvalidError: If the invitation was already accepted.
            ConflictError: If an account with this email already exists.
        """
        with self._sessions.transaction() as db:
            claimed = db.execute(
                update(InvitationRow)
                .where(
                    InvitationRow.id == invitation.id,
                    InvitationRow.org_id == invitation.org_id,
                    InvitationRow.accepted_at.is_(None),
                )
                .values(accepted_at=datetime.now(UTC))
            )
            if _rowcount(claimed) != 1:
                raise InvitationInvalidError("invitation is invalid, expired or already used")
            _insert_user(db, user, password_hash)
        return user


def _rowcount(result: Result[Any]) -> int:
    """Rows affected by an UPDATE/DELETE (DML statements return a ``CursorResult``)."""
    return cast(CursorResult[Any], result).rowcount


class SqlRunRepository:
    """Stores :class:`PipelineRun` metadata, scoped by organization."""

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
                    dataset_id=run.dataset_id,
                    request_payload=run.spec.model_dump(mode="json"),
                    error=run.error,
                    created_at=run.created_at,
                    finished_at=run.finished_at,
                )
            )
        return run

    def update(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        """Update an existing run.

        Args:
            org_id: Owning organization (enforced).
            run: The run with new field values.

        Returns:
            The stored run.

        Raises:
            NotFoundError: If the run does not exist for this org.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(RunRow).where(RunRow.id == run.id, RunRow.org_id == org_id)
            ).first()
            if row is None:
                raise NotFoundError(f"run {run.id} not found for org {org_id}")
            row.status = run.status.value
            row.dataset_id = run.dataset_id
            row.error = run.error
            row.finished_at = run.finished_at
        return run

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
            row = session.scalars(
                select(RunRow).where(RunRow.id == run_id, RunRow.org_id == org_id)
            ).first()
            if row is None:
                raise NotFoundError(f"run {run_id} not found for org {org_id}")
            return _run_from_row(row)

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


def _run_from_row(row: RunRow) -> PipelineRun:
    """Convert a run row to its contract."""
    return PipelineRun(
        id=row.id,
        org_id=row.org_id,
        spec=SourceSpec.model_validate(row.request_payload),
        status=RunStatus(row.status),
        dataset_id=row.dataset_id,
        error=row.error,
        created_at=_as_utc(row.created_at),
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
            StorageError: If a record has no ``record_key``, or on a
                duplicate key within the dataset.
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
        """Delete every row belonging to an organization (privacy).

        Args:
            org_id: Organization whose data is being deleted.

        Returns:
            Number of datasets deleted.
        """
        with self._sessions.transaction() as session:
            dataset_ids = list(
                session.scalars(select(DatasetRow.id).where(DatasetRow.org_id == org_id))
            )
            session.execute(delete(EnrichmentResultRow).where(EnrichmentResultRow.org_id == org_id))
            session.execute(delete(FeatureVectorRow).where(FeatureVectorRow.org_id == org_id))
            session.execute(delete(ValidationIssueRow).where(ValidationIssueRow.org_id == org_id))
            session.execute(delete(QualityReportRow).where(QualityReportRow.org_id == org_id))
            session.execute(delete(NormalizedRecordRow).where(NormalizedRecordRow.org_id == org_id))
            session.execute(delete(DatasetRow).where(DatasetRow.org_id == org_id))
            session.execute(delete(RunRow).where(RunRow.org_id == org_id))
            return len(dataset_ids)


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
        """Store feature vectors.

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
                    fingerprint_bits=v.fingerprint_bits,
                    fingerprint_radius=v.fingerprint_radius,
                    fingerprint_n_bits=v.fingerprint_n_bits,
                    created_at=datetime.now(UTC),
                )
                for v in vectors
            )
        return len(vectors)


class SqlEnrichmentRepository:
    """Stores enrichment results."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def save_many(self, org_id: uuid.UUID, results: Sequence[EnrichmentResult]) -> int:
        """Store enrichment results.

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


def build_sql_repositories(engine: object) -> Repositories:
    """Build the full repository bundle on one engine.

    Args:
        engine: Engine to bind to.

    Returns:
        SQL-backed repositories.
    """
    sessions = SessionFactory(engine)  # type: ignore[arg-type]
    return Repositories(
        organizations=SqlOrganizationRepository(sessions),
        api_keys=SqlApiKeyRepository(sessions),
        users=SqlUserRepository(sessions),
        sessions=SqlSessionRepository(sessions),
        invitations=SqlInvitationRepository(sessions),
        runs=SqlRunRepository(sessions),
        datasets=SqlDatasetRepository(sessions),
        reports=SqlQualityReportRepository(sessions),
        features=SqlFeatureRepository(sessions),
        enrichments=SqlEnrichmentRepository(sessions),
    )
