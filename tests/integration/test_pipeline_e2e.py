"""End-to-end: ingest -> validate -> store -> featurize -> enrich -> export.

Runs on a real Alembic-migrated SQLite database through the real
composition root, exercising every source with recorded fixtures.
"""

import pytest

from dndlabs.core.schemas import Organization, RunStatus, SourceSpec, SourceType
from dndlabs.pipeline.factory import Container
from tests.conftest import ASPIRIN_KEY, FIXTURES


def _org(container: Container, name: str = "Acme") -> Organization:
    return container.repositories.organizations.create(Organization(name=name))


async def test_pubchem_sample_end_to_end(container: Container) -> None:
    org = _org(container)
    run = container.service.submit(
        org.id,
        SourceSpec(
            source=SourceType.PUBCHEM, identifiers=["2244", "3672", "2519"], dataset_name="nsaids"
        ),
    )
    finished = await container.service.execute(org.id, run.id)
    assert finished.status is RunStatus.SUCCEEDED

    report = container.repositories.reports.get_for_dataset(org.id, finished.dataset_id)
    assert (report.total_records, report.accepted_records) == (3, 3)
    assert report.issues == []

    dataset = container.repositories.datasets.get(org.id, finished.dataset_id)
    assert [r.source_record_id for r in dataset.records] == ["2244", "3672", "2519"]
    aspirin = dataset.records[0]
    assert aspirin.name == "Aspirin"
    assert aspirin.record_key == ASPIRIN_KEY
    assert aspirin.molecular_formula == "C9H8O4"

    from sqlalchemy import func, select

    from dndlabs.storage.models import FeatureVectorRow

    with container.repositories.features._sessions.transaction() as session:  # type: ignore[attr-defined]
        count = session.scalar(select(func.count()).select_from(FeatureVectorRow))
    assert count == 3

    enrichment = container.repositories.enrichments.get_for_dataset(org.id, finished.dataset_id)
    assert all(e.status == "skipped_no_key" for e in enrichment)


async def test_chembl_target_end_to_end(container: Container) -> None:
    org = _org(container)
    run = container.service.submit(
        org.id, SourceSpec(source=SourceType.CHEMBL, chembl_target="CHEMBL204")
    )
    finished = await container.service.execute(org.id, run.id)
    assert finished.status is RunStatus.SUCCEEDED
    dataset = container.repositories.datasets.get(org.id, finished.dataset_id)
    assert len(dataset.records) == 3
    aspirin = next(r for r in dataset.records if r.source_record_id == "CHEMBL25")
    assert aspirin.activity_value_nm == 1500.0
    assert aspirin.target == "CHEMBL204"


async def test_malformed_csv_end_to_end(container: Container) -> None:
    org = _org(container)
    run = container.service.submit(
        org.id,
        SourceSpec(source=SourceType.CSV, csv_path=str(FIXTURES / "lab_export_malformed.csv")),
    )
    finished = await container.service.execute(org.id, run.id)
    report = container.repositories.reports.get_for_dataset(org.id, finished.dataset_id)
    assert report.total_records == 5
    assert report.accepted_records == 3
    assert report.rejected_records == 2
    assert report.duplicate_records == 0


async def test_json_upload_end_to_end(container: Container) -> None:
    org = _org(container)
    run = container.service.submit(
        org.id,
        SourceSpec(source=SourceType.JSON, json_path=str(FIXTURES / "data_lake_upload.json")),
    )
    finished = await container.service.execute(org.id, run.id)
    report = container.repositories.reports.get_for_dataset(org.id, finished.dataset_id)
    assert report.accepted_records == 1
    assert report.rejected_records == 1


async def test_two_orgs_are_fully_isolated(container: Container) -> None:
    org_a, org_b = _org(container, "A"), _org(container, "B")
    run_a = container.service.submit(
        org_a.id, SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244"])
    )
    finished_a = await container.service.execute(org_a.id, run_a.id)

    assert container.repositories.datasets.list_for_org(org_b.id) == []
    with pytest.raises(Exception, match="not found"):
        container.repositories.datasets.get(org_b.id, finished_a.dataset_id)
    with pytest.raises(Exception, match="not found"):
        container.repositories.runs.get(org_b.id, run_a.id)


async def test_export_is_schema_valid_csv(container: Container) -> None:
    from dndlabs.core.schemas import ExportFormat, NormalizedRecord
    from dndlabs.pipeline.exporter import EXPORT_COLUMNS

    org = _org(container)
    run = container.service.submit(
        org.id, SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244"])
    )
    finished = await container.service.execute(org.id, run.id)
    dataset = container.repositories.datasets.get(org.id, finished.dataset_id)
    body = container.exporter.export(dataset.records, ExportFormat.CSV)

    import io

    import pandas as pd

    frame = pd.read_csv(io.BytesIO(body), dtype=str, keep_default_na=False)
    assert tuple(frame.columns) == EXPORT_COLUMNS
    for row in frame.to_dict(orient="records"):
        NormalizedRecord.model_validate({k: (v or None) for k, v in row.items()})
