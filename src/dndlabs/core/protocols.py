"""Protocols (structural interfaces) that decouple the layers.

Every repository method takes an explicit ``org_id`` argument — never
optional, never inferred client-side — so no call can accidentally cross
tenants. See docs/architecture.md.
"""

import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from dndlabs.core.schemas import (
    ApiKeyRecord,
    CompoundProfile,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentRequest,
    EnrichmentResult,
    ExportFormat,
    FeatureVector,
    Invitation,
    InvitationPurpose,
    MappingTemplate,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RawRecord,
    Role,
    RuleOutcome,
    SourceSpec,
    SourceType,
    StoredFeatures,
    Upload,
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
class OrgScopedConnector(Protocol):
    """A connector whose input belongs to an organization (e.g. its uploaded files)."""

    source: SourceType

    def fetch_for_org(self, org_id: uuid.UUID, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Fetch raw records described by ``spec`` from ``org_id``'s data.

        Args:
            org_id: The organization running the pipeline (enforced).
            spec: What to ingest.

        Returns:
            An async iterator of raw, unvalidated records.

        Raises:
            IngestionError: If the input cannot be read.
            NotFoundError: If the input does not belong to ``org_id``.
        """
        ...


class StructureResolver(Protocol):
    """Finds structures for records that identify them only indirectly.

    Records with SMILES or InChI pass through unchanged. Others get
    ``smiles`` from a MOL block, or by looking up their InChIKey, PubChem
    CID, ChEMBL ID or name, with ``structure_source`` saying where it came
    from; records that cannot be resolved get ``structure_error`` instead.
    """

    async def resolve(
        self,
        raws: Sequence[RawRecord],
        checkpoint: Callable[[int], None] | None = None,
    ) -> list[RawRecord]:
        """Resolve structures; never raises for an unresolvable record.

        Args:
            raws: Records from a connector.
            checkpoint: Called with the number of records resolved so far
                after each lookup, so a run can stop mid-stage; whatever it
                raises propagates and stops resolution.

        Returns:
            The same records, in order, with structures filled in or an
            explanation of why not.
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

    def export(
        self,
        records: Iterable[NormalizedRecord],
        fmt: ExportFormat,
        profiles: Mapping[uuid.UUID, CompoundProfile] | None = None,
    ) -> bytes:
        """Render records.

        Args:
            records: Records to export, in export order.
            fmt: Output format.
            profiles: Computed properties by record id, exported alongside.

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

    def list_members(self, org_id: uuid.UUID) -> list[User]:
        """List an organization's users, oldest first.

        Args:
            org_id: Organization (enforced).

        Returns:
            The users.
        """
        ...

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
        ...

    def delete(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Delete a user and, by cascade, their sessions.

        Args:
            org_id: Owning organization (enforced).
            user_id: User identifier.

        Raises:
            NotFoundError: If the user does not exist in this org.
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

    def list_pending(
        self, org_id: uuid.UUID, purpose: InvitationPurpose, now: datetime
    ) -> list[Invitation]:
        """List an organization's unredeemed, unrevoked, unexpired tokens, newest first.

        Args:
            org_id: Organization (enforced).
            purpose: Which kind of token to list.
            now: Current time (tokens expiring at or before it are excluded).

        Returns:
            The pending tokens.
        """
        ...

    def revoke(self, org_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        """Revoke a pending token so it can no longer be redeemed.

        Args:
            org_id: Owning organization (enforced).
            invitation_id: Token to revoke.

        Raises:
            NotFoundError: If no unredeemed, unrevoked token has this id in this org.
        """
        ...

    def redeem_password_reset(self, invitation: Invitation, password_hash: str) -> User:
        """Redeem a password-reset token, in one transaction.

        Marks the token used, sets the password of the user with the token's
        email in its org, clears any sign-in lock, and deletes all of that
        user's sessions.

        Args:
            invitation: The (valid, unexpired) reset token being redeemed.
            password_hash: Argon2 hash of the new password.

        Returns:
            The user whose password was reset.

        Raises:
            InvitationInvalidError: If the token was already used or revoked,
                or its account no longer exists.
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
            InvitationInvalidError: If the invitation was already accepted or revoked.
            ConflictError: If an account with this email already exists.
        """
        ...


class UploadRepository(Protocol):
    """Persistence of uploaded files, scoped by organization."""

    def create(self, upload: Upload, data: bytes) -> Upload:
        """Store an uploaded file.

        Args:
            upload: Its metadata.
            data: Its content.

        Returns:
            The stored metadata.
        """
        ...

    def get(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> Upload:
        """Fetch an upload's metadata.

        Args:
            org_id: Owning organization (enforced).
            upload_id: Upload identifier.

        Returns:
            The metadata.

        Raises:
            NotFoundError: If the upload does not exist in this org.
        """
        ...

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
        ...


class MappingTemplateRepository(Protocol):
    """Persistence of saved column mappings, scoped by organization."""

    def create(self, template: MappingTemplate) -> MappingTemplate:
        """Store a template, replacing any of the org's templates with the same name.

        Args:
            template: The template.

        Returns:
            The stored template.
        """
        ...

    def list_templates(self, org_id: uuid.UUID) -> list[MappingTemplate]:
        """List an organization's templates, by name.

        Args:
            org_id: Organization (enforced).

        Returns:
            The templates.
        """
        ...

    def delete(self, org_id: uuid.UUID, template_id: uuid.UUID) -> None:
        """Delete a template.

        Args:
            org_id: Owning organization (enforced).
            template_id: Template identifier.

        Raises:
            NotFoundError: If the template does not exist in this org.
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
        """Update an existing run's outcome.

        Writes ``status``, ``stage``, ``progress``, ``dataset_id``, ``error``
        and ``finished_at``. ``attempts`` and ``cancel_requested`` belong to
        the queue and to cancellation, and are never overwritten here.

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

    def request_cancel(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        """Cancel a run: a pending one at once, a running one at its next checkpoint.

        A finished run is returned unchanged.

        Args:
            org_id: Owning organization (enforced).
            run_id: Run to cancel.

        Returns:
            The run after the request.

        Raises:
            NotFoundError: If the run does not exist for this org.
        """
        ...

    def claim(
        self, org_id: uuid.UUID, run_id: uuid.UUID, worker_id: str, lease_seconds: float
    ) -> PipelineRun | None:
        """Atomically claim one pending run for ``worker_id`` (e.g. the CLI's own run).

        Args:
            org_id: Owning organization (enforced).
            run_id: The run.
            worker_id: The claiming worker.
            lease_seconds: How long the claim lasts unless renewed.

        Returns:
            The claimed run, or ``None`` if it is no longer pending.
        """
        ...

    # The queue methods below serve the run worker, which executes every
    # organization's runs; each run it claims carries its own ``org_id``,
    # which scopes everything the worker then does for it.

    def claim_next(
        self, worker_id: str, lease_seconds: float, max_lost_leases: int
    ) -> PipelineRun | None:
        """Atomically claim the next runnable run for ``worker_id``.

        Runnable: pending, or running under a lease that has expired (its
        worker crashed, was killed or hung) unless that worker was the
        ``max_lost_leases``-th to stop that way (see :meth:`fail_exhausted`).
        Among runnable runs, the one whose organization has the fewest runs
        executing right now is taken first, oldest first on a tie, so one
        organization's backlog cannot hold up everyone else's runs.

        The run becomes ``running`` with one more attempt and a new lease.
        Concurrent callers never claim the same run.

        Args:
            worker_id: The claiming worker.
            lease_seconds: How long the claim lasts unless renewed.
            max_lost_leases: Unexpected worker stops after which a run is
                failed rather than claimed again.

        Returns:
            The claimed run, or ``None`` if nothing is runnable.
        """
        ...

    def fail_exhausted(self, max_lost_leases: int) -> list[PipelineRun]:
        """Fail runs whose worker has now stopped unexpectedly ``max_lost_leases`` times.

        A run counts a lost lease each time its lease expires while it is
        running; with ``max_lost_leases=3`` the third such stop fails it
        instead of letting it be claimed again, and deletes whatever its
        attempts stored. Clean shutdowns hand runs back with :meth:`release`
        and never count.

        Args:
            max_lost_leases: Which unexpected worker stop fails a run (3: the third).

        Returns:
            The runs marked failed.
        """
        ...

    def renew_lease(self, run_id: uuid.UUID, worker_id: str, lease_seconds: float) -> bool:
        """Extend a running run's lease, if ``worker_id`` still holds it.

        Args:
            run_id: The run.
            worker_id: The worker executing it.
            lease_seconds: New lease length from now.

        Returns:
            Whether the lease was renewed (``False``: the run finished, was
            deleted, or another worker took it over).
        """
        ...

    def release(self, run_id: uuid.UUID, worker_id: str) -> None:
        """Hand an unfinished run back to the queue after a clean stop.

        The run becomes ``pending`` again, keeping its stage, progress and
        attempts, so the next poll claims it at once; unlike an expired
        lease, this does not count against it. Whatever the stopped attempt
        stored is deleted (the next attempt starts from the source anyway).
        A run whose cancellation was requested ends ``cancelled`` instead.
        Does nothing if ``worker_id`` no longer holds the run.

        Args:
            run_id: The run.
            worker_id: The worker that held it.
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

    def delete_for_run(self, org_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        """Delete the dataset a run produced, with everything that references it.

        Used before a run is executed again, so an interrupted attempt never
        leaves a partial dataset behind.

        Args:
            org_id: Owning organization (enforced).
            run_id: The run.

        Returns:
            Whether a dataset was deleted.
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

    def features_for(
        self, org_id: uuid.UUID, record_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, StoredFeatures]:
        """Return the stored descriptors and alerts of the given records.

        Args:
            org_id: Owning organization; other organizations' vectors are
                never returned.
            record_ids: The records.

        Returns:
            Stored features by record id, for the records that have a vector.
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
    uploads: UploadRepository
    mapping_templates: MappingTemplateRepository
    runs: RunRepository
    datasets: DatasetRepository
    reports: QualityReportRepository
    features: FeatureRepository
    enrichments: EnrichmentRepository
