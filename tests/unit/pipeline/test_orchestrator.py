import uuid

import pytest
from tests.fakes import DictProvider, StaticConnector, fake_repositories

from dndlabs.core.exceptions import PipelineError, StorageError
from dndlabs.core.schemas import RawRecord, RunStatus, SourceSpec, SourceType
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
    finished = await service.execute(ORG_ID, run.id)
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
    finished = await service.execute(ORG_ID, run.id)
    dataset = service._repos.datasets.get(ORG_ID, finished.dataset_id)  # type: ignore[arg-type]
    assert dataset.dataset.name == f"csv-{str(run.id)[:8]}"


async def test_submit_then_execute() -> None:
    service = _service()
    run = service.submit(ORG_ID, SPEC)
    assert service._repos.runs.get(ORG_ID, run.id).status is RunStatus.PENDING  # type: ignore[attr-defined]
    finished = await service.execute(ORG_ID, run.id)
    assert finished.status is RunStatus.SUCCEEDED


async def test_ingestion_failure_marks_run_failed() -> None:
    service = _service(error="source down")
    run = service.submit(ORG_ID, SPEC)
    with pytest.raises(PipelineError, match="source down"):
        await service.execute(ORG_ID, run.id)
    failed = service._repos.runs.get(ORG_ID, run.id)  # type: ignore[attr-defined]
    assert failed.status is RunStatus.FAILED
    assert failed.error == "source down"


async def test_background_execution_swallows_errors() -> None:
    service = _service(error="boom")
    run = service.submit(ORG_ID, SPEC)
    await service.execute_in_background(ORG_ID, run.id)
    assert service._repos.runs.get(ORG_ID, run.id).status is RunStatus.FAILED  # type: ignore[attr-defined]


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
        await service.execute(ORG_ID, run.id)


async def test_enrichment_enabled_reflects_client() -> None:
    assert _service().enrichment_enabled() is False
