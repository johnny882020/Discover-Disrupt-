"""Pipeline orchestrator: ingest, resolve structures, validate, store, featurize, enrich.

:class:`PipelineService` queues runs (``submit``) and executes a run a worker
has claimed (``execute``), recording its stage and counts as it goes. Every
attempt starts from the source: a previous attempt's partial dataset is
deleted first, because resuming half-stored output could duplicate or lose
records. Long stages call a checkpoint periodically, so a cancellation or a
worker shutdown takes effect within one batch rather than at the next stage.
If the organization's data is deleted while a run executes, the run stops
quietly and removes whatever it stored.
"""

import uuid
from collections.abc import Callable, Sequence
from typing import Protocol

from dndlabs.core.exceptions import (
    DndLabsError,
    EnrichmentError,
    IngestionError,
    NotFoundError,
    PipelineError,
    RunDeletedError,
    RunInterruptedError,
    StorageError,
    ValidationError,
)
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import (
    Connector,
    EnrichmentClient,
    Featurizer,
    OrgScopedConnector,
    Repositories,
    StructureResolver,
)
from dndlabs.core.schemas import (
    Dataset,
    PipelineRun,
    RawRecord,
    RunStage,
    RunStatus,
    SourceSpec,
    SourceType,
    ValidationOutcome,
    new_id,
    utcnow,
)
from dndlabs.enrichment.service import EnrichmentService

logger = get_logger(__name__)

#: Records featurized and stored per batch; a run can stop between batches.
#: Matches the validator's checkpoint interval: large enough that progress
#: writes are negligible, small enough that a stop request waits seconds.
_CHUNK = 500


class ConnectorProvider(Protocol):
    """Looks up the connector for a source."""

    def get(self, source: SourceType) -> Connector | OrgScopedConnector:
        """Return the connector for ``source``.

        Args:
            source: Requested source.

        Returns:
            The connector.
        """
        ...


class RecordValidator(Protocol):
    """Validates a batch of raw records."""

    def run(
        self,
        run_id: uuid.UUID,
        dataset_id: uuid.UUID,
        raws: Sequence[RawRecord],
        checkpoint: Callable[[int], None] | None = None,
    ) -> ValidationOutcome:
        """Validate records.

        Args:
            run_id: Owning run.
            dataset_id: Dataset the accepted records will belong to.
            raws: Raw records.
            checkpoint: Called with the count validated so far, periodically;
                what it raises stops validation.

        Returns:
            Accepted records and the quality report.
        """
        ...


class PipelineService:
    """Runs pipelines and records their lifecycle in storage, scoped by organization."""

    def __init__(
        self,
        connectors: ConnectorProvider,
        validator: RecordValidator,
        repositories: Repositories,
        featurizer: Featurizer | None = None,
        enrichment_client: EnrichmentClient | None = None,
        resolver: StructureResolver | None = None,
    ) -> None:
        """Wire the service.

        Args:
            connectors: Connector lookup.
            validator: Record validator.
            repositories: Storage.
            featurizer: Feature extractor; the featurize stage is skipped if ``None``.
            enrichment_client: Enrichment client; a null client is used if ``None``.
            resolver: Structure resolver; records are validated as fetched if ``None``.
        """
        self._connectors = connectors
        self._validator = validator
        self._repos = repositories
        self._featurizer = featurizer
        self._resolver = resolver
        self._enrichment = EnrichmentService(enrichment_client)

    def enrichment_enabled(self) -> bool:
        """Whether real NVIDIA enrichment calls will be made.

        Returns:
            True if a real (non-null) enrichment client is configured.
        """
        return self._enrichment.is_enabled()

    def submit(self, org_id: uuid.UUID, spec: SourceSpec) -> PipelineRun:
        """Queue a run without executing it; a run worker picks it up.

        Args:
            org_id: Owning organization.
            spec: What to ingest.

        Returns:
            The pending run.

        Raises:
            NotFoundError: If the spec names an upload the org does not have.
        """
        if spec.upload_id is not None:
            self._repos.uploads.get(org_id, spec.upload_id)  # fail fast, before the run exists
        return self._repos.runs.create(PipelineRun(org_id=org_id, spec=spec))

    async def execute(
        self,
        org_id: uuid.UUID,
        run_id: uuid.UUID,
        interrupted: Callable[[], bool] = lambda: False,
    ) -> PipelineRun:
        """Execute a run its caller has claimed from the queue.

        Anything a previous, interrupted attempt stored is deleted first, so
        every attempt starts from the source. Between stages the run's stage
        and counts are recorded, and a cancellation request or ``interrupted``
        stops it, there or at a checkpoint within a long stage.

        Args:
            org_id: Owning organization.
            run_id: The claimed (``running``) run.
            interrupted: Whether the caller must stop (shutdown, lost lease);
                checked between stages and at every checkpoint.

        Returns:
            The finished run: succeeded, or cancelled on request.

        Raises:
            RunInterruptedError: If ``interrupted`` stopped it; the worker
                releases the run back to the queue (or its lease expires).
            RunDeletedError: If the run was deleted with its organization's
                data while executing; what it stored has been removed.
            PipelineError: If the run is not claimed, or any stage fails (the
                failure is recorded on the run).
        """
        run = self._repos.runs.get(org_id, run_id)
        if run.status is not RunStatus.RUNNING:
            raise PipelineError(f"run {run_id} is {run.status.value}, not claimed for execution")
        logger.info(
            "run started",
            extra={"run_id": str(run.id), "source": run.spec.source.value, "attempt": run.attempts},
        )
        progress = _Progress(self._repos, org_id, run, interrupted)
        try:
            return await self._execute_claimed(org_id, progress)
        except _RunDeletedError:
            # The org's data was deleted (DELETE /orgs/me/data) mid-run. The
            # database's foreign keys already refuse or cascade most of what
            # this run stored; deleting by run id catches the rest, so nothing
            # of the org outlives the deletion. There is no row to mark.
            try:
                self._repos.datasets.delete_for_run(org_id, run.id)
            except DndLabsError:
                logger.exception(
                    "could not remove a deleted run's output", extra={"run_id": str(run.id)}
                )
            logger.info("run deleted while executing; stopped", extra={"run_id": str(run.id)})
            raise RunDeletedError(f"run {run.id} was deleted while executing") from None

    async def _execute_claimed(self, org_id: uuid.UUID, progress: "_Progress") -> PipelineRun:
        """Execute the stages, then record the outcome: succeeded, cancelled or failed."""
        run = progress.run
        try:
            finished = await self._execute_stages(org_id, progress)
        except Exception as exc:  # every outcome is recorded on the run, or re-raised
            # Checked first, because a deleted run surfaces as whatever the
            # next write hit (a missing run, a foreign-key violation), and
            # must not be reported, marked failed or resumed.
            if self._deleted(org_id, run.id):
                raise _RunDeletedError from exc
            if isinstance(exc, RunInterruptedError):
                logger.warning("run interrupted; it will be resumed", extra={"run_id": str(run.id)})
                raise
            if isinstance(exc, _CancelledError):
                return self._record_cancelled(org_id, progress.run)
            self._mark_failed(org_id, progress.run, exc)
            if isinstance(exc, PipelineError):
                raise
            raise PipelineError(f"run {run.id} failed: {exc}") from exc
        logger.info(
            "run succeeded", extra={"run_id": str(run.id), "dataset_id": str(finished.dataset_id)}
        )
        return finished

    async def _execute_stages(self, org_id: uuid.UUID, progress: "_Progress") -> PipelineRun:
        """Run ingest, structure resolution, validate, store, featurize and enrich."""
        run = progress.run
        # Delete before retry: an interrupted attempt may have stored part of
        # its output, and a run has at most one dataset, so start clean.
        self._repos.datasets.delete_for_run(org_id, run.id)

        progress.enter(RunStage.FETCHING)
        connector = self._connectors.get(run.spec.source)
        records = (
            connector.fetch_for_org(org_id, run.spec)
            if isinstance(connector, OrgScopedConnector)
            else connector.fetch(run.spec)
        )
        raws = [raw async for raw in records]
        progress.count(fetched=len(raws))

        if self._resolver is not None:
            progress.enter(RunStage.RESOLVING)
            unresolved = sum(1 for raw in raws if not (raw.smiles or raw.inchi))
            raws = await self._resolver.resolve(
                raws, lambda done: progress.checkpoint(resolved=done)
            )
            still = sum(1 for raw in raws if not (raw.smiles or raw.inchi))
            progress.count(resolved=unresolved - still)

        progress.enter(RunStage.VALIDATING)
        dataset_id = new_id()
        outcome = self._validator.run(
            run.id, dataset_id, raws, lambda done: progress.checkpoint(validated=done)
        )
        report = outcome.report
        progress.count(
            validated=len(raws),
            accepted=report.accepted_records,
            rejected=report.rejected_records,
            duplicates=report.duplicate_records,
        )

        # Records must exist before feature_vectors/enrichment_results (FK).
        progress.enter(RunStage.STORING)
        dataset = self._repos.datasets.create(
            Dataset(
                id=dataset_id,
                org_id=org_id,
                run_id=run.id,
                name=run.spec.dataset_name or f"{run.spec.source.value}-{str(run.id)[:8]}",
                source=run.spec.source,
                record_count=len(outcome.accepted),
            ),
            outcome.accepted,
        )
        self._repos.reports.save(org_id, report)

        if self._featurizer is not None:
            progress.enter(RunStage.FEATURIZING)
            featurizable = [r for r in outcome.accepted if r.canonical_smiles]
            for start in range(0, len(featurizable), _CHUNK):
                if start:
                    progress.checkpoint(featurized=start)
                chunk = featurizable[start : start + _CHUNK]
                self._repos.features.save_many(
                    org_id, [self._featurizer.featurize(r) for r in chunk]
                )
            progress.count(featurized=len(featurizable))

        progress.enter(RunStage.ENRICHING)
        enrichment_results = await self._enrichment.enrich(
            outcome.accepted, lambda done: progress.checkpoint(enriched=done)
        )
        if enrichment_results:
            self._repos.enrichments.save_many(org_id, enrichment_results)
        progress.count(enriched=sum(1 for r in enrichment_results if r.status == "enriched"))
        return self._repos.runs.update(
            org_id,
            progress.run.model_copy(
                update={
                    "status": RunStatus.SUCCEEDED,
                    "stage": RunStage.DONE,
                    "dataset_id": dataset.id,
                    "finished_at": utcnow(),
                }
            ),
        )

    def _record_cancelled(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        """End a run cancelled on request, keeping nothing it stored."""
        try:
            self._repos.datasets.delete_for_run(org_id, run.id)
            cancelled = self._repos.runs.update(
                org_id,
                run.model_copy(update={"status": RunStatus.CANCELLED, "finished_at": utcnow()}),
            )
        except NotFoundError:
            if self._deleted(org_id, run.id):
                raise _RunDeletedError from None
            raise
        logger.info("run cancelled", extra={"run_id": str(run.id)})
        return cancelled

    def _mark_failed(self, org_id: uuid.UUID, run: PipelineRun, exc: Exception) -> None:
        """Record a failure on the run, never masking the original error.

        The run's ``error`` is returned to API clients, so it gets a fixed
        message for the kind of failure (:func:`_client_error`); the
        exception's own text, which may carry driver messages, server paths
        or third-party response fragments, is only logged.
        """
        logger.error("run failed", extra={"run_id": str(run.id), "error": str(exc)})
        try:
            self._repos.datasets.delete_for_run(org_id, run.id)
            self._repos.runs.update(
                org_id,
                run.model_copy(
                    update={
                        "status": RunStatus.FAILED,
                        "error": _client_error(exc),
                        "finished_at": utcnow(),
                    }
                ),
            )
        except NotFoundError:
            if self._deleted(org_id, run.id):  # deleted just now: nothing to record
                raise _RunDeletedError from None
            logger.exception("could not record run failure", extra={"run_id": str(run.id)})
        except DndLabsError:
            logger.exception("could not record run failure", extra={"run_id": str(run.id)})

    def _deleted(self, org_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        """Whether the run's row is gone; an unreachable database is not proof of that."""
        try:
            self._repos.runs.get(org_id, run_id)
        except NotFoundError:
            return True
        except DndLabsError:
            return False
        return False


class _RunDeletedError(Exception):
    """The run's row was deleted while it executed (internal; see ``execute``)."""


def _client_error(exc: Exception) -> str:
    """The client-safe explanation stored on a failed run, by kind of failure."""
    if isinstance(exc, IngestionError):
        return (
            "the source could not be read (unreadable data or an unavailable "
            "service); check the source and start the run again"
        )
    if isinstance(exc, ValidationError):
        return "validation could not be completed; start the run again"
    if isinstance(exc, StorageError):
        return "the results could not be stored; start the run again"
    if isinstance(exc, EnrichmentError):
        return "enrichment could not be completed; start the run again"
    return "the run stopped because of an internal error; start it again"


class _CancelledError(Exception):
    """A cancellation request stopped the run (internal; the run ends ``cancelled``)."""


class _Progress:
    """Records a run's stage and counts, and stops it when asked to.

    Every save re-reads the stored run, which is how a cancellation request
    (set by the API on the row) reaches the executing thread, and how a
    deleted run is noticed (the update finds no row).
    """

    def __init__(
        self,
        repos: Repositories,
        org_id: uuid.UUID,
        run: PipelineRun,
        interrupted: Callable[[], bool],
    ) -> None:
        self._repos = repos
        self._org_id = org_id
        self._interrupted = interrupted
        self.run = run

    def enter(self, stage: RunStage) -> None:
        """Start ``stage``, unless the run must stop first.

        Raises:
            RunInterruptedError: If the caller asked to stop.
            _CancelledError: If a cancellation was requested.
        """
        if self._interrupted():
            raise RunInterruptedError(f"run {self.run.id} interrupted before {stage.value}")
        self._save(self.run.model_copy(update={"stage": stage}))
        if self.run.cancel_requested:
            raise _CancelledError

    def checkpoint(self, **counts: int) -> None:
        """Record counts within a long stage, and stop there if asked to.

        Raises:
            RunInterruptedError: If the caller asked to stop.
            _CancelledError: If a cancellation was requested.
        """
        if self._interrupted():
            raise RunInterruptedError(
                f"run {self.run.id} interrupted during {self.run.stage.value}"
            )
        self.count(**counts)
        if self.run.cancel_requested:
            raise _CancelledError

    def count(self, **counts: int) -> None:
        """Record new counts for the current stage."""
        progress = self.run.progress.model_copy(update=counts)
        self._save(self.run.model_copy(update={"progress": progress}))

    def _save(self, run: PipelineRun) -> None:
        """Store ``run``; the stored copy carries any cancellation request."""
        self.run = self._repos.runs.update(self._org_id, run)
