import pytest
from pydantic import ValidationError as PydanticValidationError

from dndlabs.core.schemas import (
    IdentifierType,
    PipelineRun,
    QualityReport,
    RawRecord,
    RunStatus,
    SourceSpec,
    SourceType,
)


def test_pubchem_spec_requires_identifiers() -> None:
    with pytest.raises(PydanticValidationError):
        SourceSpec(source=SourceType.PUBCHEM)


def test_pubchem_cid_spec_rejects_non_numeric() -> None:
    with pytest.raises(PydanticValidationError, match="positive integers"):
        SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244", "aspirin"])


def test_pubchem_name_spec_accepts_names() -> None:
    spec = SourceSpec(
        source=SourceType.PUBCHEM, identifiers=["aspirin"], identifier_type=IdentifierType.NAME
    )
    assert spec.identifiers == ["aspirin"]


@pytest.mark.parametrize("source", [SourceType.CSV, SourceType.JSON])
def test_file_sources_require_path(source: SourceType) -> None:
    with pytest.raises(PydanticValidationError, match="requires a path"):
        SourceSpec(source=source)
    assert SourceSpec(source=source, path="x").path == "x"


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(PydanticValidationError):
        RawRecord(source=SourceType.CSV, source_record_id="1", bogus="x")  # type: ignore[call-arg]


def test_pipeline_run_defaults() -> None:
    run = PipelineRun(spec=SourceSpec(source=SourceType.CSV, path="a.csv"))
    assert run.status is RunStatus.PENDING
    assert len(run.id) == 36
    assert run.created_at.tzinfo is not None


def test_quality_report_pass_rate_bounds() -> None:
    with pytest.raises(PydanticValidationError):
        QualityReport(
            run_id="r",
            total_records=1,
            accepted_records=1,
            rejected_records=0,
            duplicate_records=0,
            warning_count=0,
            error_count=0,
            pass_rate=1.5,
        )
