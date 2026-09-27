import json
import uuid

import pandas as pd

from dndlabs.core.schemas import (
    CompoundProfile,
    ExportFormat,
    NormalizedRecord,
    PotencyClass,
    SourceType,
)
from dndlabs.pipeline.exporter import EXPORT_COLUMNS, PROPERTY_COLUMNS, DatasetExporter

DATASET_ID = uuid.uuid4()


def _records(n: int = 2) -> list[NormalizedRecord]:
    return [
        NormalizedRecord(
            dataset_id=DATASET_ID,
            record_key=f"K{i}",
            source=SourceType.CSV,
            source_record_id=str(i),
            canonical_smiles="C" * (i + 1),
            activity_value_nm=float(i),
        )
        for i in range(n)
    ]


def test_csv_has_fixed_columns() -> None:
    body = DatasetExporter().export(_records(), ExportFormat.CSV)
    import io

    frame = pd.read_csv(io.BytesIO(body))
    assert tuple(frame.columns) == EXPORT_COLUMNS
    assert list(frame["canonical_smiles"]) == ["C", "CC"]


def test_empty_csv_still_has_header() -> None:
    body = DatasetExporter().export([], ExportFormat.CSV)
    assert body.decode().strip().split(",") == list(EXPORT_COLUMNS)


def test_jsonl_roundtrip() -> None:
    body = DatasetExporter().export(_records(), ExportFormat.JSONL)
    rows = [json.loads(line) for line in body.decode().splitlines()]
    assert len(rows) == 2
    assert rows[0]["record_key"] == "K0"


def test_computed_properties_follow_the_record_fields() -> None:
    records = _records()
    profile = CompoundProfile(
        record_id=records[0].id, clogp=1.31, qed=0.55, lipinski_violations=0,
        potency_class=PotencyClass.OPTIMIZED,
    )  # fmt: skip
    exporter = DatasetExporter()

    import io

    frame = pd.read_csv(
        io.BytesIO(exporter.export(records, ExportFormat.CSV, {records[0].id: profile})),
        dtype=str,
        keep_default_na=False,
    )
    assert tuple(frame.columns[-len(PROPERTY_COLUMNS) :]) == PROPERTY_COLUMNS
    assert frame.loc[0, "clogp"] == "1.31"
    assert frame.loc[0, "potency_class"] == "optimized"
    assert frame.loc[1, "clogp"] == ""  # no profile: empty, never guessed

    rows = [
        json.loads(line)
        for line in exporter.export(records, ExportFormat.JSONL, {records[0].id: profile})
        .decode()
        .splitlines()
    ]
    assert list(rows[0]) == list(EXPORT_COLUMNS)
    assert (rows[0]["qed"], rows[1]["qed"]) == (0.55, None)
