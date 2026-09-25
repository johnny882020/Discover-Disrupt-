"""End-to-end: ingest -> validate -> store -> export, through the real stack."""

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.core.schemas import (
    DatasetWithRecords,
    NormalizedRecord,
    QualityReport,
    RunStatus,
    Severity,
    SourceSpec,
    SourceType,
)
from dndlabs.pipeline.exporter import EXPORT_COLUMNS
from dndlabs.pipeline.factory import Container
from tests.conftest import FIXTURES, PUBCHEM_12_CIDS


def test_pubchem_sample_end_to_end(container: Container) -> None:
    result = container.service.run(
        SourceSpec(source=SourceType.PUBCHEM, identifiers=PUBCHEM_12_CIDS, dataset_name="nsaids+")
    )
    assert result.run.status is RunStatus.SUCCEEDED
    report = result.report
    assert (report.total_records, report.accepted_records) == (12, 12)
    assert report.issues == []
    assert report.pass_rate == 1.0

    stored = container.repositories.datasets.get(result.dataset.id)
    assert [r.source_record_id for r in stored.records] == PUBCHEM_12_CIDS
    by_cid = {r.source_record_id: r for r in stored.records}
    aspirin = by_cid["2244"]
    assert aspirin.name == "Aspirin"
    assert aspirin.record_key == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert aspirin.molecular_formula == "C9H8O4"
    assert aspirin.molecular_weight == pytest.approx(180.16)
    assert "@" in (by_cid["156391"].canonical_smiles or "")  # naproxen keeps stereo
    assert len({r.record_key for r in stored.records}) == 12

    # Export is model-ready: fixed columns, one row per accepted record, schema-valid.
    assert result.export_path is not None
    frame = pd.read_csv(result.export_path, dtype=str, keep_default_na=False)
    assert tuple(frame.columns) == EXPORT_COLUMNS
    assert len(frame) == 12
    exported = [
        NormalizedRecord.model_validate({k: (v or None) for k, v in row.items()})
        for row in frame.to_dict(orient="records")
    ]
    assert exported == stored.records

    raws = container.repositories.raw_records.list_for_run(result.run.id)
    assert len(raws) == 12 and raws[0].extra == {"pubchem_cid": 2244}


def test_malformed_csv_end_to_end(container: Container) -> None:
    result = container.service.run(
        SourceSpec(source=SourceType.CSV, path=str(FIXTURES / "lab_export_malformed.csv"))
    )
    report = container.repositories.reports.get_for_dataset(result.dataset.id)
    assert report == result.report
    assert report.total_records == 12
    assert report.accepted_records == 5
    assert report.rejected_records == 6
    assert report.duplicate_records == 1
    assert (report.error_count, report.warning_count) == (6, 1)
    assert report.issues_by_rule == {
        "compound_identity": 1,
        "duplicates": 1,
        "schema": 1,
        "unit_normalization": 4,
    }
    assert report.pass_rate == pytest.approx(5 / 12, abs=1e-4)
    errors = {i.source_record_id: i.field for i in report.issues if i.severity is Severity.ERROR}
    assert errors == {
        "LAB-005": "smiles",
        "LAB-006": "activity_unit",
        "LAB-007": "activity_value",
        "LAB-008": "smiles",
        "LAB-009": "activity_unit",
        "LAB-012": "activity_value",
    }
    [dup] = [i for i in report.issues if i.rule == "duplicates"]
    assert dup.source_record_id == "LAB-004" and "LAB-003" in dup.message

    records = container.repositories.datasets.get(result.dataset.id).records
    assert {r.source_record_id: r.activity_value_nm for r in records} == {
        "LAB-001": 1500.0,
        "LAB-002": 2500.0,
        "LAB-003": 2000.0,
        "LAB-010": 0.5,
        "LAB-011": None,
    }


def test_json_upload_end_to_end(container: Container) -> None:
    result = container.service.run(
        SourceSpec(source=SourceType.JSON, path=str(FIXTURES / "data_lake_upload.json"))
    )
    assert result.report.accepted_records == 2
    assert result.report.rejected_records == 2  # SMILES/InChI mismatch, no structure
    records = container.repositories.datasets.get(result.dataset.id).records
    assert [r.activity_value_nm for r in records] == [3200.0, 40000.0]


def test_api_end_to_end(container: Container) -> None:
    services = ApiServices(
        repositories=container.repositories, runner=container.service, renderer=container.exporter
    )
    with TestClient(create_app(services)) as client:
        submitted = client.post(
            "/pipelines/run", json={"source": "pubchem", "identifiers": ["2244", "3672", "5090"]}
        )
        assert submitted.status_code == 202
        run = client.get(f"/pipelines/runs/{submitted.json()['id']}").json()
        assert run["status"] == "succeeded"

        dataset = DatasetWithRecords.model_validate(
            client.get(f"/datasets/{run['dataset_id']}").json()
        )
        # The recorded response holds 12 CIDs; the pipeline stores what PubChem returns.
        assert dataset.dataset.record_count == len(dataset.records) == 12
        report = QualityReport.model_validate(
            client.get(f"/datasets/{run['dataset_id']}/quality-report").json()
        )
        assert report.dataset_id == run["dataset_id"]
        jsonl = client.get(f"/datasets/{run['dataset_id']}/export", params={"format": "jsonl"})
        assert len([json.loads(line) for line in jsonl.text.splitlines()]) == 12
