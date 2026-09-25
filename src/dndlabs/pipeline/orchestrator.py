"""Pipeline orchestrator: ingest -> validate -> filter/featurize -> enrich -> store."""

import uuid
from collections.abc import Sequence
from typing import Protocol

from dndlabs.core.exceptions import DndLabsError, PipelineError
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import Connector, EnrichmentClient, Featurizer, Repositories
from dndlabs.core.schemas import (
    Dataset,
    PipelineRun,
    RawRecord,
    RunStatus,
    SourceSpec,
    SourceType,
    ValidationOutcome,
    new_id,
    utcnow,
)
from dndlabs.enrichment.service import EnrichmentService

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

    def run(
        self, run_id: uuid.UUID, dataset_id: uuid.UUID, raws: Sequence[RawRecord]
    ) -> ValidationOutcome:
        """Validate records.

        Args:
            run_id: Owning run.
            dataset_id: Dataset the accepted records will belong to.
            raws: Raw records.

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
    ) -> None:
        """Wire the service.

        Args:
            connectors: Connector lookup.
            validator: Record validator.
            repositories: Storage.
            featurizer: Feature extractor; the featurize stage is skipped if ``None``.
            enrichment_client: Enrichment client; a null client is used if ``None``.
        """
        self._connectors = connectors
        self._validator = validator
        self._repos = repositories
        self._featurizer = featurizer
        self._enrichment = EnrichmentService(enrichment_client)

    def submit(self, org_id: uuid.UUID, spec: SourceSpec) -> PipelineRun:
        """Register a pending run without executing it.

        Args:
            org_id: Owning organization.
            spec: What to ingest.

        Returns:
            The pending run.
        """
        return self._repos.runs.create(PipelineRun(org_id=org_id, spec=spec))

    async def execute(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        """Execute a previously submitted run.

        Args:
            org_id: Owning organization.
            run_id: Run to execute.

        Returns:
            The finished run.

        Raises:
            PipelineError: If any stage fails.
        """
        run = self._repos.runs.update(
            org_id,
            self._repos.runs.get(org_id, run_id).model_copy(update={"status": RunStatus.RUNNING}),
        )
        logger.info("run started", extra={"run_id": str(run.id), "source": run.spec.source.value})
        try:
            finished = await self._execute_stages(org_id, run)
        except Exception as exc:  # every failure must be recorded on the run; re-raised below
            self._mark_failed(org_id, run, exc)
            if isinstance(exc, PipelineError):
                raise
            raise PipelineError(f"run {run.id} failed: {exc}") from exc
        logger.info(
            "run succeeded", extra={"run_id": str(run.id), "dataset_id": str(finished.dataset_id)}
        )
        return finished

    async def execute_in_background(self, org_id: uuid.UUID, run_id: uuid.UUID) -> None:
        """Execute a run, logging instead of raising (for background tasks).

        Args:
            org_id: Owning organization.
            run_id: Run to execute.
        """
        try:
            await self.execute(org_id, run_id)
        except DndLabsError:
            logger.exception("background run failed", extra={"run_id": str(run_id)})

    async def _execute_stages(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        """Run ingest, validate, featurize, enrich and store for ``run``."""
        raws = []
        async for raw in self._connectors.get(run.spec.source).fetch(run.spec):
            raws.append(raw)

        dataset_id = new_id()
        outcome = self._validator.run(run.id, dataset_id, raws)

        if self._featurizer is not None:
            vectors = [
                self._featurizer.featurize(r) for r in outcome.accepted if r.canonical_smiles
            ]
            if vectors:
                self._repos.features.save_many(org_id, vectors)

        enrichment_results = await self._enrichment.enrich(outcome.accepted)
        if enrichment_results:
            self._repos.enrichments.save_many(org_id, enrichment_results)

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
        self._repos.reports.save(org_id, outcome.report)
        return self._repos.runs.update(
            org_id,
            run.model_copy(
                update={
                    "status": RunStatus.SUCCEEDED,
                    "dataset_id": dataset.id,
                    "finished_at": utcnow(),
                }
            ),
        )

    def _mark_failed(self, org_id: uuid.UUID, run: PipelineRun, exc: Exception) -> None:
        """Record a failure on the run, never masking the original error."""
        logger.error("run failed", extra={"run_id": str(run.id), "error": str(exc)})
        try:
            self._repos.runs.update(
                org_id,
                run.model_copy(
                    update={"status": RunStatus.FAILED, "error": str(exc), "finished_at": utcnow()}
                ),
            )
        except DndLabsError:
            logger.exception("could not record run failure", extra={"run_id": str(run.id)})
