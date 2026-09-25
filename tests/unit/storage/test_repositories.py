from datetime import UTC, datetime

import pytest

from dndlabs.core.exceptions import NotFoundError, StorageError
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    Dataset,
    NormalizedRecord,
    PipelineRun,
    QualityReport,
    RawRecord,
    RunStatus,
    Severity,
    SourceSpec,
    SourceType,
    ValidationIssue,
)


def _run() -> PipelineRun:
    return PipelineRun(spec=SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244"]))


def _record(key: str, sid: str = "1") -> NormalizedRecord:
    return NormalizedRecord(
        record_key=key,
        source=SourceType.PUBCHEM,
        source_record_id=sid,
        canonical_smiles="CC(=O)Oc1ccccc1C(=O)O",
        inchikey=key,
        molecular_weight=180.16,
    )


def test_run_create_get_update(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    fetched = repos.runs.get(run.id)
    assert fetched == run
    done = run.model_copy(
        update={"status": RunStatus.SUCCEEDED, "finished_at": datetime.now(UTC), "dataset_id": "d"}
    )
    repos.runs.update(done)
    assert repos.runs.get(run.id).status is RunStatus.SUCCEEDED
    assert repos.runs.get(run.id).finished_at is not None


def test_run_missing(repos: Repositories) -> None:
    with pytest.raises(NotFoundError):
        repos.runs.get("nope")
    with pytest.raises(NotFoundError):
        repos.runs.update(_run())


def test_raw_records_roundtrip(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    raws = [
        RawRecord(source=SourceType.CSV, source_record_id=str(i), smiles="C", extra={"k": i})
        for i in range(3)
    ]
    assert repos.raw_records.add_many(run.id, raws) == 3
    assert repos.raw_records.list_for_run(run.id) == raws


def test_raw_records_require_existing_run(repos: Repositories) -> None:
    with pytest.raises(StorageError):
        repos.raw_records.add_many(
            "missing", [RawRecord(source=SourceType.CSV, source_record_id="1")]
        )


def test_dataset_roundtrip_preserves_order(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    records = [_record("B" * 27, "2"), _record("A" * 27, "1")]
    ds = repos.datasets.create(
        Dataset(run_id=run.id, name="demo", source=SourceType.PUBCHEM, record_count=2), records
    )
    fetched = repos.datasets.get(ds.id)
    assert fetched.dataset == ds
    assert fetched.records == records
    assert [d.id for d in repos.datasets.list()] == [ds.id]


def test_dataset_rejects_duplicate_keys_atomically(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    ds = Dataset(run_id=run.id, name="demo", source=SourceType.PUBCHEM, record_count=2)
    with pytest.raises(StorageError):
        repos.datasets.create(ds, [_record("A" * 27), _record("A" * 27)])
    assert repos.datasets.list() == []


def test_dataset_rejects_record_without_key(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    ds = Dataset(run_id=run.id, name="demo", source=SourceType.PUBCHEM, record_count=1)
    bad = _record("A" * 27).model_copy(update={"record_key": None})
    with pytest.raises(StorageError, match="record_key"):
        repos.datasets.create(ds, [bad])


def test_dataset_missing(repos: Repositories) -> None:
    with pytest.raises(NotFoundError):
        repos.datasets.get("nope")


def test_quality_report_roundtrip(repos: Repositories) -> None:
    run = repos.runs.create(_run())
    ds = repos.datasets.create(
        Dataset(run_id=run.id, name="d", source=SourceType.PUBCHEM, record_count=0), []
    )
    report = QualityReport(
        run_id=run.id,
        dataset_id=ds.id,
        total_records=2,
        accepted_records=1,
        rejected_records=1,
        duplicate_records=0,
        warning_count=0,
        error_count=1,
        issues_by_rule={"schema": 1},
        issues=[
            ValidationIssue(
                rule="schema", severity=Severity.ERROR, source_record_id="2", message="bad"
            )
        ],
        pass_rate=0.5,
    )
    repos.reports.save(report)
    assert repos.reports.get_for_dataset(ds.id) == report


def test_quality_report_requires_dataset(repos: Repositories) -> None:
    report = QualityReport(
        run_id="r",
        total_records=0,
        accepted_records=0,
        rejected_records=0,
        duplicate_records=0,
        warning_count=0,
        error_count=0,
        pass_rate=0.0,
    )
    with pytest.raises(StorageError):
        repos.reports.save(report)
    with pytest.raises(NotFoundError):
        repos.reports.get_for_dataset("nope")
