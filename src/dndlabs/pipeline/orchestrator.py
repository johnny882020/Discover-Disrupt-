"""Pipeline orchestrator: ingest -> validate -> store -> export."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from dndlabs.core.exceptions import DndLabsError, PipelineError
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import Connector, Repositories
from dndlabs.core.schemas import (
    Dataset,
    DatasetWithRecords,
    ExportFormat,
    PipelineRun,
    RawRecord,
    RunResult,
    RunStatus,
    SourceSpec,
    SourceType,
    ValidationOutcome,
    utcnow,
)

logger = get_logger(__name__)


class ConnectorProvider(Protocol):
    """Looks up the connector for a source."""

    def get(self, source: SourceType) -> Connector:
        """Return the connector for ``source``.

        Args:
            source: Requested source.

        Returns:
            The connector.
        """
        ...


class RecordValidator(Protocol):
    """Validates a batch of raw records."""

    def run(self, run_id: str, raws: Sequence[RawRecord]) -> ValidationOutcome:
        """Validate records.

        Args:
            run_id: Owning run.
            raws: Raw records.

        Returns:
            Accepted records and the quality report.
        """
        ...


class Exporter(Protocol):
    """Writes datasets to files."""

    def write(self, dataset: DatasetWithRecords, fmt: ExportFormat, directory: Path) -> Path:
        """Export a dataset.

        Args:
            dataset: Dataset to export.
            fmt: Output format.
            directory: Target directory.

        Returns:
            The written file.
        """
        ...


class PipelineService:
    """Runs pipelines and records their lifecycle in storage."""

    def __init__(
        self,
        connectors: ConnectorProvider,
        validator: RecordValidator,
        repositories: Repositories,
        exporter: Exporter | None = None,
        export_dir: Path | None = None,
        export_format: ExportFormat = ExportFormat.CSV,
    ) -> None:
        """Wire the service.

        Args:
            connectors: Connector lookup.
            validator: Record validator.
            repositories: Storage.
            exporter: Exporter; export is skipped when ``None``.
            export_dir: Directory for exported files.
            export_format: Default export format.
        """
        self._connectors = connectors
        self._validator = validator
        self._repos = repositories
        self._exporter = exporter
        self._export_dir = export_dir
        self._export_format = export_format

    def submit(self, spec: SourceSpec) -> PipelineRun:
        """Register a pending run without executing it.

        Args:
            spec: What to ingest.

        Returns:
            The pending run.
        """
        return self._repos.runs.create(PipelineRun(spec=spec))

    def run(self, spec: SourceSpec) -> RunResult:
        """Submit and synchronously execute a run.

        Args:
            spec: What to ingest.

        Returns:
            The run result.

        Raises:
            PipelineError: If the run fails.
        """
        return self.execute(self.submit(spec).id)

    def execute(self, run_id: str) -> RunResult:
        """Execute a previously submitted run.

        The run is marked ``running``, then ``succeeded`` or ``failed``; the
        failure reason is stored on the run.

        Args:
            run_id: Run to execute.

        Returns:
            The run result.

        Raises:
            PipelineError: If any stage fails.
        """
        run = self._repos.runs.update(
            self._repos.runs.get(run_id).model_copy(update={"status": RunStatus.RUNNING})
        )
        logger.info("run started", extra={"run_id": run.id, "source": run.spec.source.value})
        try:
            result = self._execute_stages(run)
        except Exception as exc:  # every failure must be recorded on the run; re-raised below
            self._mark_failed(run, exc)
            if isinstance(exc, PipelineError):
                raise
            raise PipelineError(f"run {run.id} failed: {exc}") from exc
        logger.info(
            "run succeeded",
            extra={"run_id": run.id, "dataset_id": result.dataset.id},
        )
        return result

    def execute_in_background(self, run_id: str) -> None:
        """Execute a run, logging instead of raising (for background tasks).

        Args:
            run_id: Run to execute.
        """
        try:
            self.execute(run_id)
        except DndLabsError:
            logger.exception("background run failed", extra={"run_id": run_id})

    def _execute_stages(self, run: PipelineRun) -> RunResult:
        """Run ingest, validate, store and export for ``run``."""
        raws = self._connectors.get(run.spec.source).fetch(run.spec)
        self._repos.raw_records.add_many(run.id, raws)
        outcome = self._validator.run(run.id, raws)
        dataset = self._repos.datasets.create(
            Dataset(
                run_id=run.id,
                name=run.spec.dataset_name or f"{run.spec.source.value}-{run.id[:8]}",
                source=run.spec.source,
                record_count=len(outcome.accepted),
            ),
            outcome.accepted,
        )
        report = self._repos.reports.save(
            outcome.report.model_copy(update={"dataset_id": dataset.id})
        )
        export_path = self._export(DatasetWithRecords(dataset=dataset, records=outcome.accepted))
        finished = self._repos.runs.update(
            run.model_copy(
                update={
                    "status": RunStatus.SUCCEEDED,
                    "dataset_id": dataset.id,
                    "finished_at": utcnow(),
                }
            )
        )
        return RunResult(run=finished, dataset=dataset, report=report, export_path=export_path)

    def _export(self, dataset: DatasetWithRecords) -> Path | None:
        """Export the dataset if an exporter is configured."""
        if self._exporter is None or self._export_dir is None:
            return None
        return self._exporter.write(dataset, self._export_format, self._export_dir)

    def _mark_failed(self, run: PipelineRun, exc: Exception) -> None:
        """Record a failure on the run, never masking the original error."""
        logger.error("run failed", extra={"run_id": run.id, "error": str(exc)})
        try:
            self._repos.runs.update(
                run.model_copy(
                    update={"status": RunStatus.FAILED, "error": str(exc), "finished_at": utcnow()}
                )
            )
        except DndLabsError:
            logger.exception("could not record run failure", extra={"run_id": run.id})
