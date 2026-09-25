"""Protocols (structural interfaces) that decouple the layers.

Implementations live in ``ingestion``, ``validation`` and ``storage``; the
orchestrator, API and CLI depend only on these protocols.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from dndlabs.core.schemas import (
    Dataset,
    DatasetRuleOutcome,
    DatasetWithRecords,
    NormalizedRecord,
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

    def fetch(self, spec: SourceSpec) -> list[RawRecord]:
        """Fetch raw records described by ``spec``.

        Args:
            spec: What to ingest.

        Returns:
            The raw, unvalidated records.

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
class DatasetRule(Protocol):
    """A validation rule that needs to see the whole dataset."""

    name: str

    def apply(self, records: Sequence[NormalizedRecord]) -> DatasetRuleOutcome:
        """Validate a collection of records.

        Args:
            records: Records that passed all record-level rules.

        Returns:
            Records kept, records dropped, and issues found.
        """
        ...


class RunRepository(Protocol):
    """Persistence of pipeline run metadata."""

    def create(self, run: PipelineRun) -> PipelineRun:
        """Insert a new run.

        Args:
            run: The run to store.

        Returns:
            The stored run.
        """
        ...

    def update(self, run: PipelineRun) -> PipelineRun:
        """Update an existing run.

        Args:
            run: The run with new field values.

        Returns:
            The stored run.

        Raises:
            NotFoundError: If the run does not exist.
        """
        ...

    def get(self, run_id: str) -> PipelineRun:
        """Fetch a run by id.

        Args:
            run_id: Run identifier.

        Returns:
            The run.

        Raises:
            NotFoundError: If the run does not exist.
        """
        ...


class RawRecordRepository(Protocol):
    """Persistence of raw records for lineage and reprocessing."""

    def add_many(self, run_id: str, records: Sequence[RawRecord]) -> int:
        """Store raw records for a run.

        Args:
            run_id: Owning run.
            records: Records to store.

        Returns:
            Number of records stored.
        """
        ...

    def list_for_run(self, run_id: str) -> list[RawRecord]:
        """List raw records of a run in insertion order.

        Args:
            run_id: Owning run.

        Returns:
            The raw records.
        """
        ...


class DatasetRepository(Protocol):
    """Persistence of normalized datasets."""

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        """Store a dataset and its records.

        Args:
            dataset: Dataset metadata.
            records: Normalized records, in export order.

        Returns:
            The stored dataset.
        """
        ...

    def get(self, dataset_id: str) -> DatasetWithRecords:
        """Fetch a dataset with its records.

        Args:
            dataset_id: Dataset identifier.

        Returns:
            The dataset and its records.

        Raises:
            NotFoundError: If the dataset does not exist.
        """
        ...

    def list(self) -> list[Dataset]:
        """List all datasets, newest first.

        Returns:
            Dataset metadata.
        """
        ...


class QualityReportRepository(Protocol):
    """Persistence of per-run quality reports."""

    def save(self, report: QualityReport) -> QualityReport:
        """Store a quality report.

        Args:
            report: The report; ``dataset_id`` must be set.

        Returns:
            The stored report.
        """
        ...

    def get_for_dataset(self, dataset_id: str) -> QualityReport:
        """Fetch the quality report of a dataset.

        Args:
            dataset_id: Dataset identifier.

        Returns:
            The report.

        Raises:
            NotFoundError: If no report exists for the dataset.
        """
        ...


@dataclass(frozen=True)
class Repositories:
    """Bundle of repositories handed to services and delivery layers."""

    runs: RunRepository
    raw_records: RawRecordRepository
    datasets: DatasetRepository
    reports: QualityReportRepository
