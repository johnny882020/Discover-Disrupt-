"""Protocols (structural interfaces) that decouple the layers.

Every repository method takes an explicit ``org_id`` argument — never
optional, never inferred client-side — so no call can accidentally cross
tenants. See docs/architecture.md.
"""

import uuid
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
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
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RawRecord,
    RuleOutcome,
    SourceSpec,
    SourceType,
)


@runtime_checkable
class Connector(Protocol):
    """Fetches raw records from one kind of source."""

    source: SourceType

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Fetch raw records described by ``spec``.

        Args:
            spec: What to ingest.

        Yields:
            Raw, unvalidated records.

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
    runs: RunRepository
    datasets: DatasetRepository
    reports: QualityReportRepository
    features: FeatureRepository
    enrichments: EnrichmentRepository
