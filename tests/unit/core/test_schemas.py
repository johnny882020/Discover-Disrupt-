import uuid

import pytest
from pydantic import ValidationError

from dndlabs.core.schemas import (
    NormalizedRecord,
    PipelineRun,
    QualityReport,
    RawRecord,
    RunStatus,
    SourceSpec,
    SourceType,
)


def test_pubchem_spec_requires_identifiers() -> None:
    with pytest.raises(ValidationError):
        SourceSpec(source=SourceType.PUBCHEM)


def test_chembl_spec_requires_no_extra_fields_but_needs_no_validation() -> None:
    spec = SourceSpec(source=SourceType.CHEMBL, chembl_target="CHEMBL204")
    assert spec.chembl_target == "CHEMBL204"


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RawRecord(source=SourceType.CSV, source_record_id="1", bogus="x")  # type: ignore[call-arg]


def test_pipeline_run_defaults() -> None:
    org_id = uuid.uuid4()
    run = PipelineRun(org_id=org_id, spec=SourceSpec(source=SourceType.CSV, csv_path="a.csv"))
    assert run.status is RunStatus.PENDING
    assert run.created_at.tzinfo is not None


def test_quality_report_pass_rate_bounds() -> None:
    with pytest.raises(ValidationError):
        QualityReport(
            run_id=uuid.uuid4(), total_records=1, accepted_records=1, rejected_records=0,
            duplicate_records=0, warning_count=0, error_count=0, pass_rate=1.5,
        )  # fmt: skip


def test_normalized_record_requires_dataset_id() -> None:
    with pytest.raises(ValidationError):
        NormalizedRecord(source=SourceType.CSV, source_record_id="1")  # type: ignore[call-arg]
