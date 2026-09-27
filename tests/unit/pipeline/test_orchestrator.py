import uuid
from collections.abc import Callable, Sequence

import pytest
from tests.fakes import DictProvider, StaticConnector, fake_repositories

from dndlabs.core.exceptions import (
    NotFoundError,
    PipelineError,
    RunDeletedError,
    RunInterruptedError,
    StorageError,
)
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    EnrichmentRequest,
    EnrichmentResult,
    PipelineRun,
    RawRecord,
    RunProgress,
    RunStage,
    RunStatus,
    SourceSpec,
    SourceType,
)
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.preprocessing.featurize import RdkitFeaturizer
from dndlabs.validation.validator import Validator

ORG_ID = uuid.uuid4()
SPEC = SourceSpec(source=SourceType.CSV, csv_path="lab.csv", dataset_name="demo")
RAWS = [
    RawRecord(source=SourceType.CSV, source_record_id="1", smiles="CCO"),
    RawRecord(source=SourceType.CSV, source_record_id="2", smiles="OCC"),  # duplicate
    RawRecord(source=SourceType.CSV, source_record_id="3", smiles="C1CC("),  # invalid
]


def _claim(service: PipelineService, run: PipelineRun) -> PipelineRun:
    """Claim ``run`` as a worker would before executing it."""
    claimed = service._repos.runs.claim(run.org_id, run.id, "test-worker", 60)
    assert claimed is not None
    return claimed


async def _execute(service: PipelineService, run: PipelineRun) -> PipelineRun:
    return await service.execute(run.org_id, _claim(service, run).id)


def _service(**connector_kwargs: object) -> PipelineService:
    connector = StaticConnector(SourceType.CSV, RAWS, **connector_kwargs)  # type: ignore[arg-type]
    return PipelineService(
        connectors=DictProvider(connector),
        validator=Validator(),
        repositories=fake_repositories(),
        featurizer=RdkitFeaturizer(),
    )


async def test_run_success_end_to_end() -> None:
    service = _service()
    run = service.submit(ORG_ID, SPEC)
    finished = await _execute(service, run)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.finished_at is not None
    dataset = service._repos.datasets.get(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert dataset.dataset.name == "demo"
    assert dataset.dataset.record_count == 1
    report = service._repos.reports.get_for_dataset(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert (report.duplicate_records, report.rejected_records) == (1, 1)
    assert len(service._repos.features.items) == 1  # type: ignore[attr-defined]
    enrichment = service._repos.enrichments.items  # type: ignore[attr-defined]
    assert enrichment[0].status == "skipped_no_key"


async def test_default_dataset_name() -> None:
    service = _service()
    run = service.submit(ORG_ID, SourceSpec(source=SourceType.CSV, csv_path="x.csv"))
    finished = await _execute(service, run)
    dataset = service._repos.datasets.get(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert dataset.dataset.name == f"csv-{str(run.id)[:8]}"


async def test_submit_then_execute() -> None:
    service = _service()
    run = service.submit(ORG_ID, SPEC)
    assert service._repos.runs.get(ORG_ID, run.id).status is RunStatus.PENDING  # type: ignore[attr-defined]
    finished = await _execute(service, run)
    assert finished.status is RunStatus.SUCCEEDED


async def test_ingestion_failure_marks_run_failed() -> None:
    service = _service(error="source down")
    run = service.submit(ORG_ID, SPEC)
    with pytest.raises(PipelineError, match="source down"):
        await _execute(service, run)
    failed = service._repos.runs.get(ORG_ID, run.id)  # type: ignore[attr-defined]
    assert failed.status is RunStatus.FAILED
    assert failed.error == "source down"


async def test_an_unclaimed_run_is_not_executed() -> None:
    service = _service()
    run = service.submit(ORG_ID, SPEC)
    with pytest.raises(PipelineError, match="not claimed"):
        await service.execute(ORG_ID, run.id)
    assert service._repos.runs.get(ORG_ID, run.id).status is RunStatus.PENDING  # type: ignore[attr-defined]


async def test_stage_and_counts_are_recorded() -> None:
    service = _service()
    finished = await _execute(service, service.submit(ORG_ID, SPEC))
    assert finished.stage is RunStage.DONE
    assert finished.progress == RunProgress(
        fetched=3, validated=3, accepted=1, rejected=1, duplicates=1, featurized=1, enriched=0
    )
    assert finished.attempts == 1 and finished.started_at is not None


async def test_stages_are_entered_in_order() -> None:
    service = _service()
    runs = service._repos.runs  # type: ignore[attr-defined]
    stages: list[RunStage] = []
    original_update = runs.update

    def recording_update(org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        if not stages or stages[-1] is not run.stage:
            stages.append(run.stage)
        return original_update(org_id, run)

    runs.update = recording_update
    await _execute(service, service.submit(ORG_ID, SPEC))
    assert stages == [
        RunStage.FETCHING,
        RunStage.VALIDATING,
        RunStage.STORING,
        RunStage.FEATURIZING,
        RunStage.ENRICHING,
        RunStage.DONE,
    ]


async def test_a_cancel_request_stops_the_run_and_keeps_nothing() -> None:
    service = _service()
    run = _claim(service, service.submit(ORG_ID, SPEC))
    runs = service._repos.runs  # type: ignore[attr-defined]
    original_update = runs.update

    def cancel_while_validating(org_id: uuid.UUID, r: PipelineRun) -> PipelineRun:
        stored = original_update(org_id, r)
        if r.stage is RunStage.STORING and r.status is RunStatus.RUNNING:
            runs.request_cancel(org_id, r.id)
            return runs.get(org_id, r.id)
        return stored

    runs.update = cancel_while_validating
    finished = await service.execute(ORG_ID, run.id)
    assert finished.status is RunStatus.CANCELLED
    assert finished.dataset_id is None and finished.error is None
    assert service._repos.datasets.items == {}  # type: ignore[attr-defined]


async def test_an_interrupted_run_stays_running_for_the_queue() -> None:
    service = _service()
    run = _claim(service, service.submit(ORG_ID, SPEC))
    with pytest.raises(RunInterruptedError):
        await service.execute(ORG_ID, run.id, interrupted=lambda: True)
    stored = service._repos.runs.get(ORG_ID, run.id)  # type: ignore[attr-defined]
    assert stored.status is RunStatus.RUNNING and stored.error is None


async def test_a_resumed_run_replaces_what_the_interrupted_attempt_stored() -> None:
    service = _service()
    run = _claim(service, service.submit(ORG_ID, SPEC))
    calls = iter([False] * 4 + [True])  # stop before enriching: the dataset exists
    with pytest.raises(RunInterruptedError):
        await service.execute(ORG_ID, run.id, interrupted=lambda: next(calls))
    assert len(service._repos.datasets.items) == 1  # type: ignore[attr-defined]

    runs = service._repos.runs  # type: ignore[attr-defined]
    runs.release(run.id, "test-worker")
    resumed = runs.claim_next("other-worker", 60, max_lost_leases=3)
    assert resumed is not None and resumed.attempts == 2
    finished = await service.execute(ORG_ID, run.id)
    assert finished.status is RunStatus.SUCCEEDED
    assert list(service._repos.datasets.items) == [finished.dataset_id]  # type: ignore[attr-defined]


async def test_failure_recording_error_does_not_mask_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(error="source down")
    run = service.submit(ORG_ID, SPEC)
    runs = service._repos.runs  # type: ignore[attr-defined]
    original_update = runs.update

    def flaky_update(org_id, r):  # type: ignore[no-untyped-def]
        if r.status is RunStatus.FAILED:
            raise StorageError("db gone")
        return original_update(org_id, r)

    monkeypatch.setattr(runs, "update", flaky_update)
    with pytest.raises(PipelineError, match="source down"):
        await _execute(service, run)


async def test_enrichment_enabled_reflects_client() -> None:
    assert _service().enrichment_enabled() is False


async def test_upload_run_reads_the_orgs_file_with_the_run_mapping() -> None:
    from dndlabs.core.exceptions import NotFoundError
    from dndlabs.core.schemas import ColumnRole
    from dndlabs.ingestion.uploads import UploadConnector, UploadService

    repos = fake_repositories()
    uploads = UploadService(repos.uploads, repos.mapping_templates)
    upload = uploads.store(ORG_ID, "lab.csv", b"id,structure\nA-1,CCO\nA-2,C1CC(\n").upload
    service = PipelineService(
        connectors=DictProvider(UploadConnector(repos.uploads)),
        validator=Validator(),
        repositories=repos,
    )
    spec = SourceSpec(
        source=SourceType.UPLOAD,
        upload_id=upload.id,
        column_mapping={"id": ColumnRole.SOURCE_RECORD_ID, "structure": ColumnRole.SMILES},
    )

    finished = await _execute(service, service.submit(ORG_ID, spec))

    assert finished.status is RunStatus.SUCCEEDED
    dataset = repos.datasets.get(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert [r.source_record_id for r in dataset.records] == ["A-1"]
    assert dataset.dataset.source is SourceType.UPLOAD
    report = repos.reports.get_for_dataset(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert report.rejected_records == 1

    with pytest.raises(NotFoundError):  # another org's upload is refused before a run exists
        service.submit(uuid.uuid4(), spec)


async def test_structures_are_resolved_before_validation() -> None:
    import httpx
    from tests.conftest import FIXTURES

    from dndlabs.core.schemas import ColumnRole
    from dndlabs.ingestion.http import RetryPolicy
    from dndlabs.ingestion.resolution import LookupStructureResolver
    from dndlabs.ingestion.uploads import UploadConnector, UploadService

    def pubchem(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=(FIXTURES / "pubchem" / "properties_3.json").read_bytes()
        )

    def offline(request: httpx.Request) -> httpx.Response:
        raise AssertionError("ChEMBL must not be called")

    repos = fake_repositories()
    uploads = UploadService(repos.uploads, repos.mapping_templates)
    upload = uploads.store(ORG_ID, "lab.csv", b"id,cid\nA-1,2244\nA-2,999\n").upload
    service = PipelineService(
        connectors=DictProvider(UploadConnector(repos.uploads)),
        validator=Validator(),
        repositories=repos,
        resolver=LookupStructureResolver(
            httpx.Client(base_url="https://pubchem.test", transport=httpx.MockTransport(pubchem)),
            httpx.Client(base_url="https://chembl.test", transport=httpx.MockTransport(offline)),
            retry=RetryPolicy(sleep=lambda _: None),
        ),
    )
    spec = SourceSpec(
        source=SourceType.UPLOAD,
        upload_id=upload.id,
        column_mapping={"id": ColumnRole.SOURCE_RECORD_ID, "cid": ColumnRole.PUBCHEM_CID},
    )

    finished = await _execute(service, service.submit(ORG_ID, spec))

    assert finished.status is RunStatus.SUCCEEDED
    dataset = repos.datasets.get(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    [record] = dataset.records
    assert (record.source_record_id, record.inchikey) == ("A-1", "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
    report = repos.reports.get_for_dataset(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    lookups = {(i.source_record_id, i.severity.value, i.message) for i in report.issues
               if i.rule == "structure_lookup"}  # fmt: skip
    assert lookups == {
        ("A-1", "warning", "structure from PubChem CID 2244"),
        ("A-2", "error", "PubChem has no compound with CID 999"),
    }


def _ethanol(index: int) -> RawRecord:
    return RawRecord(source=SourceType.CSV, source_record_id=str(index), smiles="CCO")


async def test_a_long_stage_stops_at_its_next_checkpoint() -> None:
    raws = [
        RawRecord(source=SourceType.CSV, source_record_id=str(i), smiles="CCO") for i in range(6)
    ]
    repos = fake_repositories()
    service = PipelineService(
        DictProvider(StaticConnector(SourceType.CSV, raws)),
        Validator(checkpoint_every=2),
        repos,
    )
    run = _claim(service, service.submit(ORG_ID, SPEC))
    runs = repos.runs
    original_update = runs.update

    def cancel_after_first_checkpoint(org_id: uuid.UUID, r: PipelineRun) -> PipelineRun:
        stored = original_update(org_id, r)
        if stored.progress.validated == 2:
            return runs.request_cancel(org_id, r.id)
        return stored

    runs.update = cancel_after_first_checkpoint  # type: ignore[method-assign]
    finished = await service.execute(ORG_ID, run.id)
    assert (finished.status, finished.stage) == (RunStatus.CANCELLED, RunStage.VALIDATING)
    assert finished.progress.validated == 2  # stopped mid-stage, not after all 6


async def test_an_interrupt_stops_a_long_stage_mid_way() -> None:
    raws = [
        RawRecord(source=SourceType.CSV, source_record_id=str(i), smiles="CCO") for i in range(6)
    ]
    repos = fake_repositories()
    service = PipelineService(
        DictProvider(StaticConnector(SourceType.CSV, raws)),
        Validator(checkpoint_every=2),
        repos,
    )
    run = _claim(service, service.submit(ORG_ID, SPEC))
    stages_entered = iter([False, False])  # fetching, validating; then the first checkpoint

    def interrupted() -> bool:
        return next(stages_entered, True)

    with pytest.raises(RunInterruptedError, match="during validating"):
        await service.execute(ORG_ID, run.id, interrupted)


def _cancel_when(repos: Repositories, reached: Callable[[PipelineRun], bool]) -> None:
    """Request cancellation the first time a stored run satisfies ``reached``."""
    runs = repos.runs
    original_update = runs.update

    def update(org_id: uuid.UUID, r: PipelineRun) -> PipelineRun:
        stored = original_update(org_id, r)
        if stored.status is RunStatus.RUNNING and reached(stored):
            return runs.request_cancel(org_id, r.id)
        return stored

    runs.update = update  # type: ignore[method-assign]


class _SlowResolver:
    """Resolves one record per 'request', reporting each to the checkpoint."""

    def __init__(self) -> None:
        self.requests = 0

    async def resolve(
        self, raws: Sequence[RawRecord], checkpoint: Callable[[int], None] | None = None
    ) -> list[RawRecord]:
        resolved = []
        for raw in raws:
            self.requests += 1
            resolved.append(raw.model_copy(update={"smiles": "CCO"}))
            if checkpoint is not None:
                checkpoint(len(resolved))
        return resolved


async def test_a_cancel_request_stops_structure_resolution_mid_way() -> None:
    raws = [
        RawRecord(source=SourceType.CSV, source_record_id=str(i), lookup_name=f"n{i}")
        for i in range(5)
    ]
    repos = fake_repositories()
    resolver = _SlowResolver()
    service = PipelineService(
        DictProvider(StaticConnector(SourceType.CSV, raws)), Validator(), repos, resolver=resolver
    )
    run = _claim(service, service.submit(ORG_ID, SPEC))
    _cancel_when(repos, lambda r: r.progress.resolved == 2)
    finished = await service.execute(ORG_ID, run.id)
    assert (finished.status, finished.stage) == (RunStatus.CANCELLED, RunStage.RESOLVING)
    assert (finished.progress.resolved, resolver.requests) == (2, 2)  # not all 5


class _EnabledClient:
    """A real (enabled) enrichment client that enriches everything."""

    def __init__(self) -> None:
        self.batches = 0

    def is_enabled(self) -> bool:
        return True

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        self.batches += 1
        return [EnrichmentResult(record_id=r.record_id, status="enriched") for r in requests]


async def test_a_cancel_request_stops_enrichment_between_batches() -> None:
    raws = [  # 25 distinct alkanes: three enrichment batches of up to 10
        RawRecord(source=SourceType.CSV, source_record_id=str(n), smiles="C" * n)
        for n in range(1, 26)
    ]
    repos = fake_repositories()
    client = _EnabledClient()
    service = PipelineService(
        DictProvider(StaticConnector(SourceType.CSV, raws)),
        Validator(),
        repos,
        enrichment_client=client,
    )
    run = _claim(service, service.submit(ORG_ID, SPEC))
    _cancel_when(repos, lambda r: r.progress.enriched == 10)
    finished = await service.execute(ORG_ID, run.id)
    assert (finished.status, finished.stage) == (RunStatus.CANCELLED, RunStage.ENRICHING)
    assert (finished.progress.enriched, client.batches) == (10, 1)
    assert repos.datasets.items == {} and repos.enrichments.items == []  # type: ignore[attr-defined]


async def test_a_run_deleted_mid_way_stops_quietly_and_keeps_nothing() -> None:
    service = _service()
    repos = service._repos
    run = _claim(service, service.submit(ORG_ID, SPEC))
    runs = repos.runs
    original_update = runs.update

    def delete_while_featurizing(org_id: uuid.UUID, r: PipelineRun) -> PipelineRun:
        if r.stage is RunStage.FEATURIZING:  # the dataset is stored by now
            del runs.items[r.id]  # type: ignore[attr-defined]  # DELETE /orgs/me/data
        return original_update(org_id, r)

    runs.update = delete_while_featurizing  # type: ignore[method-assign]
    with pytest.raises(RunDeletedError):
        await service.execute(ORG_ID, run.id)
    assert repos.datasets.items == {}  # type: ignore[attr-defined]
    with pytest.raises(NotFoundError):
        runs.get(ORG_ID, run.id)
