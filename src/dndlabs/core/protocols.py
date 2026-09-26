"""Protocols (structural interfaces) that decouple the layers.

Every repository method takes an explicit ``org_id`` argument — never
optional, never inferred client-side — so no call can accidentally cross
tenants. See docs/architecture.md.
"""

import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from dndlabs.core.schemas import (
    ApiKeyRecord,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentRequest,
    EnrichmentResult,
    ExportFormat,
    FeatureVector,
    Invitation,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RawRecord,
    RuleOutcome,
    SourceSpec,
    SourceType,
    User,
    UserCredentials,
    UserSession,
)


@runtime_checkable
class Connector(Protocol):
    """Fetches raw records from one kind of source."""

    source: SourceType

    def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Fetch raw records described by ``spec``.

        Implementations are async generator functions: calling ``fetch``
        returns an async iterator immediately (no ``await`` before the
        ``async for``).

        Args:
            spec: What to ingest.

        Returns:
            An async iterator of raw, unvalidated records.

        Raises:
            IngestionError: If the source cannot be read.
        """
        ...


@runtime_checkable
class ValidationRule(Protocol):
    """A record-level validation/normalization rule."""

    name: str

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Validate and normalize one record.

        Args:
            raw: The original raw record.
            record: The normalized record produced by earlier rules.

        Returns:
            The (possibly updated) record and any issues found.
        """
        ...


@runtime_checkable
class Featurizer(Protocol):
    """Derives ML-ready features from a normalized record."""

    def featurize(self, record: NormalizedRecord) -> FeatureVector:
        """Compute descriptors and a fingerprint for one record.

        Args:
            record: A normalized record with a valid canonical SMILES.

        Returns:
            The feature vector.
        """
        ...


@runtime_checkable
class EnrichmentClient(Protocol):
    """Calls an external ML provider (NVIDIA BioNeMo NIM) for enrichment."""

    def is_enabled(self) -> bool:
        """Whether this client can make real calls.

        Returns:
            True if configured with credentials, False for a no-op client.
        """
        ...

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        """Enrich a batch of records.

        Args:
            requests: Records to enrich.

        Returns:
            One result per request, in the same order. Never raises for a
            single failed record; failures are reported as
            ``status="failed"`` results.
        """
        ...


@runtime_checkable
class Exporter(Protocol):
    """Serializes normalized records to a model-ready file format."""

    def export(self, records: Iterable[NormalizedRecord], fmt: ExportFormat) -> bytes:
        """Render records.

        Args:
            records: Records to export, in export order.
            fmt: Output format.

        Returns:
            The serialized bytes.
        """
        ...


class OrganizationRepository(Protocol):
    """Persistence of organizations."""

    def create(self, org: Organization) -> Organization:
        """Insert a new organization.

        Args:
            org: The organization to store.

        Returns:
            The stored organization.
        """
        ...

    def get(self, org_id: uuid.UUID) -> Organization:
        """Fetch an organization by id.

        Args:
            org_id: Organization identifier.

        Returns:
            The organization.

        Raises:
            NotFoundError: If the organization does not exist.
        """
        ...

    def ping(self) -> None:
        """Verify storage is reachable and migrated.

        Used only by the readiness probe (``GET /api/v1/health/ready``), not
        by any business logic.

        Raises:
            StorageError: If the database is unreachable or the schema is
                missing/incomplete (e.g. migrations have not run).
        """
        ...


class ApiKeyRepository(Protocol):
    """Persistence of API keys."""

    def create(self, org_id: uuid.UUID, prefix: str, hashed_key: str) -> ApiKeyRecord:
        """Store a newly issued key.

        Args:
            org_id: Owning organization.
            prefix: Non-secret lookup prefix.
            hashed_key: Argon2 hash of the raw secret (never the secret itself).

        Returns:
            The stored key record.
        """
        ...

    def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        """Look up a key by its prefix for verification.

        Args:
            prefix: Non-secret lookup prefix.

        Returns:
            The key record, or ``None`` if no such prefix exists.
        """
        ...

    def get_hash(self, prefix: str) -> str | None:
        """Fetch the stored hash for a prefix, for verification inside auth only.

        Args:
            prefix: Non-secret lookup prefix.

        Returns:
            The Argon2 hash, or ``None`` if no such prefix exists.
        """
        ...

    def touch_last_used(self, key_id: uuid.UUID) -> None:
        """Record that a key was just used.

        Args:
            key_id: Key identifier.
        """
        ...

    def revoke(self, org_id: uuid.UUID, key_id: uuid.UUID) -> None:
        """Revoke a key belonging to ``org_id``.

        Args:
            org_id: Owning organization (enforced).
            key_id: Key to revoke.

        Raises:
            NotFoundError: If the key does not exist for this org.
        """
        ...


class UserRepository(Protocol):
    """Persistence of user accounts.

    Emails are globally unique (sign-in is by email alone), so lookups by
    email are the one intentionally unscoped read; every other method takes
    ``org_id``.
    """

    def create(self, user: User, password_hash: str) -> User:
        """Insert a new user.

        Args:
            user: The user to store (``email`` already normalized).
            password_hash: Argon2 hash of the user's password.

        Returns:
            The stored user.

        Raises:
            ConflictError: If an account with this email already exists.
        """
        ...

    def get_credentials(self, email: str) -> UserCredentials | None:
        """Look up a user and their sign-in state by normalized email.

        Args:
            email: Normalized email address.

        Returns:
            The credentials, or ``None`` if no account uses this email.
        """
        ...

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
        ...

    def email_exists(self, email: str) -> bool:
        """Whether any account uses ``email``.

        Args:
            email: Normalized email address.

        Returns:
            True if an account exists.
        """
        ...

    def record_login_failure(
        self, user_id: uuid.UUID, max_attempts: int, lock_until: datetime
    ) -> None:
        """Count a failed sign-in, locking the account once ``max_attempts`` is reached.

        The increment happens in the database, so concurrent failures are
        all counted.

        Args:
            user_id: User identifier.
            max_attempts: Failures that trigger a lock.
            lock_until: When a lock triggered by this failure expires.
        """
        ...

    def record_login_success(self, user_id: uuid.UUID) -> None:
        """Reset the failure counter and any lock after a successful sign-in.

        Args:
            user_id: User identifier.
        """
        ...

    def set_password(self, org_id: uuid.UUID, user_id: uuid.UUID, password_hash: str) -> None:
        """Replace a user's password hash.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.
            password_hash: New Argon2 hash.

        Raises:
            NotFoundError: If the user does not exist in this org.
        """
        ...


class SessionRepository(Protocol):
    """Persistence of sign-in sessions, stored by token hash."""

    def create(self, session: UserSession, token_hash: str) -> UserSession:
        """Store a new session.

        Args:
            session: The session metadata.
            token_hash: SHA-256 hex digest of the bearer token.

        Returns:
            The stored session.
        """
        ...

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        """Look up a session by its token hash.

        Args:
            token_hash: SHA-256 hex digest of the presented token.

        Returns:
            The session (possibly expired or revoked), or ``None``.
        """
        ...

    def revoke(self, org_id: uuid.UUID, session_id: uuid.UUID) -> None:
        """Revoke one session of ``org_id``. Revoking an already-revoked session is a no-op.

        Args:
            org_id: Owning organization (enforced).
            session_id: Session to revoke.
        """
        ...

    def revoke_all_for_user(
        self, org_id: uuid.UUID, user_id: uuid.UUID, except_session_id: uuid.UUID | None = None
    ) -> int:
        """Revoke every active session of a user.

        Args:
            org_id: Owning organization (enforced).
            user_id: User whose sessions to revoke.
            except_session_id: A session to keep (the caller's own).

        Returns:
            Number of sessions revoked.
        """
        ...

    def delete_expired(self, before: datetime) -> int:
        """Delete sessions that expired before ``before`` (housekeeping).

        Args:
            before: Cut-off time.

        Returns:
            Number of sessions deleted.
        """
        ...


class InvitationRepository(Protocol):
    """Persistence of invitations, stored by token hash."""

    def create(self, invitation: Invitation, token_hash: str) -> Invitation:
        """Store a new invitation.

        Args:
            invitation: The invitation metadata.
            token_hash: SHA-256 hex digest of the invitation token.

        Returns:
            The stored invitation.
        """
        ...

    def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        """Look up an invitation by its token hash.

        Args:
            token_hash: SHA-256 hex digest of the presented token.

        Returns:
            The invitation (possibly expired or accepted), or ``None``.
        """
        ...

    def accept(self, invitation: Invitation, user: User, password_hash: str) -> User:
        """Redeem an invitation: mark it used and create its user, in one transaction.

        Either both happen or neither does, so a failed redemption leaves
        the invitation usable and a concurrent redemption cannot create two
        accounts.

        Args:
            invitation: The (valid, unexpired) invitation being redeemed.
            user: The user to create, in ``invitation.org_id``.
            password_hash: Argon2 hash of the chosen password.

        Returns:
            The created user.

        Raises:
            InvitationInvalidError: If the invitation was already accepted.
            ConflictError: If an account with this email already exists.
        """
        ...


class RunRepository(Protocol):
    """Persistence of pipeline run metadata, scoped by organization."""

    def create(self, run: PipelineRun) -> PipelineRun:
        """Insert a new run.

        Args:
            run: The run to store.

        Returns:
            The stored run.
        """
        ...

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
        ...

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
        ...

    def list_for_org(self, org_id: uuid.UUID) -> list[PipelineRun]:
        """List runs for an organization, newest first.

        Args:
            org_id: Owning organization.

        Returns:
            The runs.
        """
        ...


class DatasetRepository(Protocol):
    """Persistence of normalized datasets, scoped by organization."""

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        """Store a dataset and its records.

        Args:
            dataset: Dataset metadata.
            records: Normalized records, in export order.

        Returns:
            The stored dataset.
        """
        ...

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
        ...

    def list_for_org(self, org_id: uuid.UUID) -> list[Dataset]:
        """List datasets for an organization, newest first.

        Args:
            org_id: Owning organization.

        Returns:
            Dataset metadata.
        """
        ...

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
        ...

    def delete_org_data(self, org_id: uuid.UUID) -> int:
        """Delete every row belonging to an organization (privacy).

        Args:
            org_id: Organization whose data is being deleted.

        Returns:
            Number of datasets deleted.
        """
        ...


class QualityReportRepository(Protocol):
    """Persistence of per-run quality reports, scoped by organization."""

    def save(self, org_id: uuid.UUID, report: QualityReport) -> QualityReport:
        """Store a quality report.

        Args:
            org_id: Owning organization.
            report: The report; ``dataset_id`` must be set.

        Returns:
            The stored report.
        """
        ...

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
        ...


class FeatureRepository(Protocol):
    """Persistence of computed feature vectors."""

    def save_many(self, org_id: uuid.UUID, vectors: Sequence[FeatureVector]) -> int:
        """Store feature vectors.

        Args:
            org_id: Owning organization.
            vectors: Vectors to store.

        Returns:
            Number stored.
        """
        ...


class EnrichmentRepository(Protocol):
    """Persistence of enrichment results."""

    def save_many(self, org_id: uuid.UUID, results: Sequence[EnrichmentResult]) -> int:
        """Store enrichment results.

        Args:
            org_id: Owning organization.
            results: Results to store.

        Returns:
            Number stored.
        """
        ...

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> list[EnrichmentResult]:
        """Fetch enrichment results for every record in a dataset.

        Args:
            org_id: Owning organization (enforced).
            dataset_id: Dataset identifier.

        Returns:
            The enrichment results (may be empty if none were computed yet).
        """
        ...


@dataclass(frozen=True)
class Repositories:
    """Bundle of repositories handed to services and delivery layers."""

    organizations: OrganizationRepository
    api_keys: ApiKeyRepository
    users: UserRepository
    sessions: SessionRepository
    invitations: InvitationRepository
    runs: RunRepository
    datasets: DatasetRepository
    reports: QualityReportRepository
    features: FeatureRepository
    enrichments: EnrichmentRepository
