import json
from pathlib import Path

import pandas as pd
import pytest

from dndlabs.core.exceptions import ExportError
from dndlabs.core.schemas import (
    Dataset,
    DatasetWithRecords,
    ExportFormat,
    NormalizedRecord,
    SourceType,
)
from dndlabs.pipeline.exporter import EXPORT_COLUMNS, DatasetExporter


def _dataset(n: int = 2) -> DatasetWithRecords:
    records = [
        NormalizedRecord(
            record_key=f"K{i}",
            source=SourceType.CSV,
            source_record_id=str(i),
            canonical_smiles="C" * (i + 1),
            activity_value_nm=float(i),
        )
        for i in range(n)
    ]
    ds = Dataset(run_id="r", name="d", source=SourceType.CSV, record_count=n)
    return DatasetWithRecords(dataset=ds, records=records)


def test_csv_has_fixed_columns(tmp_path: Path) -> None:
    path = DatasetExporter().write(_dataset(), ExportFormat.CSV, tmp_path / "out")
    frame = pd.read_csv(path)
    assert tuple(frame.columns) == EXPORT_COLUMNS
    assert list(frame["canonical_smiles"]) == ["C", "CC"]
    assert path.name.endswith(".csv")


def test_empty_csv_still_has_header() -> None:
    text = DatasetExporter().render(_dataset(0), ExportFormat.CSV)
    assert text.strip().split(",") == list(EXPORT_COLUMNS)


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    path = DatasetExporter().write(_dataset(), ExportFormat.JSONL, tmp_path)
    rows = [
        NormalizedRecord.model_validate(json.loads(line)) for line in path.read_text().splitlines()
    ]
    assert rows == _dataset().records


def test_write_failure_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(ExportError):
        DatasetExporter().write(_dataset(), ExportFormat.CSV, blocker / "sub")
