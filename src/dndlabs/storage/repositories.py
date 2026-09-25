"""SQLAlchemy implementations of the ``core.protocols`` repositories."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, select

from dndlabs.core.exceptions import NotFoundError, StorageError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    Dataset,
    DatasetWithRecords,
    NormalizedRecord,
    PipelineRun,
    QualityReport,
    RawRecord,
    RunStatus,
    SourceSpec,
    SourceType,
)
from dndlabs.storage.database import SessionFactory
from dndlabs.storage.models import (
    DatasetRow,
    NormalizedRecordRow,
    QualityReportRow,
    RawRecordRow,
    RunRow,
)


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to naive datetimes returned by SQLite."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _run_from_row(row: RunRow) -> PipelineRun:
    """Convert a run row to its contract."""
    return PipelineRun(
        id=row.id,
        spec=SourceSpec.model_validate(row.spec),
        status=RunStatus(row.status),
        created_at=_as_utc(row.created_at),
        finished_at=_as_utc(row.finished_at) if row.finished_at else None,
        error=row.error,
        dataset_id=row.dataset_id,
    )


def _dataset_from_row(row: DatasetRow) -> Dataset:
    """Convert a dataset row to its contract."""
    return Dataset(
        id=row.id,
        run_id=row.run_id,
        name=row.name,
        source=SourceType(row.source),
        record_count=row.record_count,
        created_at=_as_utc(row.created_at),
    )


def _record_to_row(dataset_id: str, position: int, record: NormalizedRecord) -> NormalizedRecordRow:
    """Convert a normalized record to a row."""
    if record.record_key is None:
        raise StorageError(f"record {record.source_record_id!r} has no record_key")
    data = record.model_dump(mode="json")
    return NormalizedRecordRow(dataset_id=dataset_id, position=position, **data)


def _record_from_row(row: NormalizedRecordRow) -> NormalizedRecord:
    """Convert a row to a normalized record."""
    return NormalizedRecord(
        record_key=row.record_key,
        source=SourceType(row.source),
        source_record_id=row.source_record_id,
        name=row.name,
        canonical_smiles=row.canonical_smiles,
        inchi=row.inchi,
        inchikey=row.inchikey,
        molecular_formula=row.molecular_formula,
        molecular_weight=row.molecular_weight,
        activity_type=row.activity_type,
        activity_value_nm=row.activity_value_nm,
        target=row.target,
    )


class SqlRunRepository:
    """Stores :class:`PipelineRun` metadata."""

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
                    source=run.spec.source.value,
                    spec=run.spec.model_dump(mode="json"),
                    status=run.status.value,
                    error=run.error,
                    dataset_id=run.dataset_id,
                    created_at=run.created_at,
                    finished_at=run.finished_at,
                )
            )
        return run

    def update(self, run: PipelineRun) -> PipelineRun:
        """Update status, error, dataset and finish time of a run.

        Args:
            run: The run with new values.

        Returns:
            The stored run.

        Raises:
            NotFoundError: If the run does not exist.
        """
        with self._sessions.transaction() as session:
            row = session.get(RunRow, run.id)
            if row is None:
                raise NotFoundError(f"run {run.id} not found")
            row.status = run.status.value
            row.error = run.error
            row.dataset_id = run.dataset_id
            row.finished_at = run.finished_at
        return run

    def get(self, run_id: str) -> PipelineRun:
        """Fetch a run.

        Args:
            run_id: Run identifier.

        Returns:
            The run.

        Raises:
            NotFoundError: If the run does not exist.
        """
        with self._sessions.transaction() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise NotFoundError(f"run {run_id} not found")
            return _run_from_row(row)


class SqlRawRecordRepository:
    """Stores raw records for lineage."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def add_many(self, run_id: str, records: Sequence[RawRecord]) -> int:
        """Store raw records for a run.

        Args:
            run_id: Owning run.
            records: Records to store.

        Returns:
            Number of records stored.
        """
        with self._sessions.transaction() as session:
            session.add_all(
                RawRecordRow(
                    run_id=run_id,
                    source=r.source.value,
                    source_record_id=r.source_record_id,
                    payload=r.model_dump(mode="json"),
                )
                for r in records
            )
        return len(records)

    def list_for_run(self, run_id: str) -> list[RawRecord]:
        """List raw records of a run in insertion order.

        Args:
            run_id: Owning run.

        Returns:
            The raw records.
        """
        with self._sessions.transaction() as session:
            rows = session.scalars(
                select(RawRecordRow).where(RawRecordRow.run_id == run_id).order_by(RawRecordRow.id)
            )
            return [RawRecord.model_validate(row.payload) for row in rows]


class SqlDatasetRepository:
    """Stores normalized datasets and their records."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        """Store a dataset with its records atomically.

        Args:
            dataset: Dataset metadata.
            records: Normalized records, in export order.

        Returns:
            The stored dataset.
        """
        with self._sessions.transaction() as session:
            session.add(
                DatasetRow(
                    id=dataset.id,
                    run_id=dataset.run_id,
                    name=dataset.name,
                    source=dataset.source.value,
                    record_count=dataset.record_count,
                    created_at=dataset.created_at,
                )
            )
            session.flush()
            session.add_all(_record_to_row(dataset.id, i, r) for i, r in enumerate(records))
        return dataset

    def get(self, dataset_id: str) -> DatasetWithRecords:
        """Fetch a dataset with its records.

        Args:
            dataset_id: Dataset identifier.

        Returns:
            The dataset and its records in export order.

        Raises:
            NotFoundError: If the dataset does not exist.
        """
        with self._sessions.transaction() as session:
            row = session.get(DatasetRow, dataset_id)
            if row is None:
                raise NotFoundError(f"dataset {dataset_id} not found")
            record_rows = session.scalars(
                select(NormalizedRecordRow)
                .where(NormalizedRecordRow.dataset_id == dataset_id)
                .order_by(NormalizedRecordRow.position)
            )
            return DatasetWithRecords(
                dataset=_dataset_from_row(row),
                records=[_record_from_row(r) for r in record_rows],
            )

    def list(self) -> list[Dataset]:
        """List datasets, newest first.

        Returns:
            Dataset metadata.
        """
        with self._sessions.transaction() as session:
            rows = session.scalars(select(DatasetRow).order_by(DatasetRow.created_at.desc()))
            return [_dataset_from_row(r) for r in rows]


class SqlQualityReportRepository:
    """Stores per-run quality reports."""

    def __init__(self, sessions: SessionFactory) -> None:
        """Create the repository.

        Args:
            sessions: Session factory to use.
        """
        self._sessions = sessions

    def save(self, report: QualityReport) -> QualityReport:
        """Store a quality report.

        Args:
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
        return report

    def get_for_dataset(self, dataset_id: str) -> QualityReport:
        """Fetch the quality report of a dataset.

        Args:
            dataset_id: Dataset identifier.

        Returns:
            The report.

        Raises:
            NotFoundError: If no report exists for the dataset.
        """
        with self._sessions.transaction() as session:
            row = session.scalars(
                select(QualityReportRow).where(QualityReportRow.dataset_id == dataset_id)
            ).first()
            if row is None:
                raise NotFoundError(f"quality report for dataset {dataset_id} not found")
            return QualityReport.model_validate(row.report)


def build_sql_repositories(engine: Engine) -> Repositories:
    """Build the full repository bundle on one engine.

    Args:
        engine: Engine to bind to.

    Returns:
        SQL-backed repositories.
    """
    sessions = SessionFactory(engine)
    return Repositories(
        runs=SqlRunRepository(sessions),
        raw_records=SqlRawRecordRepository(sessions),
        datasets=SqlDatasetRepository(sessions),
        reports=SqlQualityReportRepository(sessions),
    )
