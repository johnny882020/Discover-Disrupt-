from pathlib import Path

import pytest

from dndlabs.core.exceptions import PipelineError, StorageError
from dndlabs.core.schemas import RawRecord, RunStatus, SourceSpec, SourceType
from dndlabs.pipeline.exporter import DatasetExporter
from dndlabs.pipeline.orchestrator import PipelineService
from dndlabs.validation.validator import Validator
from tests.fakes import DictProvider, FakeRuns, StaticConnector, fake_repositories

SPEC = SourceSpec(source=SourceType.CSV, path="lab.csv", dataset_name="demo")
RAWS = [
    RawRecord(source=SourceType.CSV, source_record_id="1", smiles="CCO"),
    RawRecord(source=SourceType.CSV, source_record_id="2", smiles="OCC"),  # duplicate
    RawRecord(source=SourceType.CSV, source_record_id="3", smiles="C1CC("),  # invalid
]


def _service(tmp_path: Path | None = None, **connector_kwargs: object) -> PipelineService:
    connector = StaticConnector(SourceType.CSV, RAWS, **connector_kwargs)  # type: ignore[arg-type]
    return PipelineService(
        connectors=DictProvider(connector),
        validator=Validator(),
        repositories=fake_repositories(),
        exporter=DatasetExporter() if tmp_path else None,
        export_dir=tmp_path,
    )


def test_run_success_end_to_end(tmp_path: Path) -> None:
    service = _service(tmp_path)
    result = service.run(SPEC)
    assert result.run.status is RunStatus.SUCCEEDED
    assert result.run.finished_at is not None
    assert result.run.dataset_id == result.dataset.id
    assert result.dataset.name == "demo"
    assert result.dataset.record_count == 1
    assert result.report.dataset_id == result.dataset.id
    assert (result.report.duplicate_records, result.report.rejected_records) == (1, 1)
    assert result.export_path is not None and result.export_path.exists()
    repos = service._repos
    assert len(repos.raw_records.list_for_run(result.run.id)) == 3
    assert repos.runs.get(result.run.id).status is RunStatus.SUCCEEDED
    assert repos.reports.get_for_dataset(result.dataset.id) == result.report


def test_default_dataset_name_and_no_export() -> None:
    result = _service().run(SourceSpec(source=SourceType.CSV, path="x.csv"))
    assert result.dataset.name == f"csv-{result.run.id[:8]}"
    assert result.export_path is None


def test_submit_then_execute() -> None:
    service = _service()
    run = service.submit(SPEC)
    assert service._repos.runs.get(run.id).status is RunStatus.PENDING
    assert service.execute(run.id).run.status is RunStatus.SUCCEEDED


def test_ingestion_failure_marks_run_failed() -> None:
    service = _service(error="source down")
    run = service.submit(SPEC)
    with pytest.raises(PipelineError, match="source down"):
        service.execute(run.id)
    failed = service._repos.runs.get(run.id)
    assert failed.status is RunStatus.FAILED
    assert failed.error == "source down"
    assert failed.finished_at is not None


def test_background_execution_swallows_errors() -> None:
    service = _service(error="boom")
    run = service.submit(SPEC)
    service.execute_in_background(run.id)
    assert service._repos.runs.get(run.id).status is RunStatus.FAILED


def test_failure_recording_error_does_not_mask_original(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(error="source down")
    run = service.submit(SPEC)
    runs = service._repos.runs
    assert isinstance(runs, FakeRuns)
    original_update = runs.update

    def flaky_update(r):  # type: ignore[no-untyped-def]
        if r.status is RunStatus.FAILED:
            raise StorageError("db gone")
        return original_update(r)

    monkeypatch.setattr(runs, "update", flaky_update)
    with pytest.raises(PipelineError, match="source down"):
        service.execute(run.id)


def test_pipeline_error_is_not_rewrapped() -> None:
    class Exploding:
        def run(self, run_id, raws):  # type: ignore[no-untyped-def]
            raise PipelineError("validator exploded")

    service = PipelineService(
        connectors=DictProvider(StaticConnector(SourceType.CSV, RAWS)),
        validator=Exploding(),
        repositories=fake_repositories(),
    )
    with pytest.raises(PipelineError, match=r"^validator exploded$"):
        service.run(SPEC)
