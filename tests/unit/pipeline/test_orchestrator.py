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

    finished = await service.execute(ORG_ID, service.submit(ORG_ID, spec).id)

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

    finished = await service.execute(ORG_ID, service.submit(ORG_ID, spec).id)

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
