from pathlib import Path

import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.csv_connector import CsvConnector


async def _fetch(path: Path) -> list:  # type: ignore[type-arg]
    return [
        r async for r in CsvConnector().fetch(SourceSpec(source=SourceType.CSV, csv_path=str(path)))
    ]


async def test_reads_csv(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text(
        "compound_id,smiles,standard_value,standard_units\nA,CCO,5,nM\n", encoding="utf-8"
    )
    [record] = await _fetch(path)
    assert record.source_record_id == "A"
    assert record.smiles == "CCO"
    assert record.activity_value == "5"


async def test_semicolon_delimiter(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("SMILES;Value\nCCO;5\n", encoding="utf-8")
    [record] = await _fetch(path)
    assert record.smiles == "CCO"


async def test_missing_identifier_column(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("name,value\nfoo,1\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="no identifier column"):
        await _fetch(path)


async def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="not found"):
        await _fetch(tmp_path / "missing.csv")


async def test_ragged_rows_raise(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text("smiles,name\nCCO,a,extra,more\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="cannot parse"):
        await _fetch(path)


async def test_rejects_wrong_spec() -> None:
    with pytest.raises(IngestionError):
        await _fetch_bad_spec()


async def _fetch_bad_spec() -> list:  # type: ignore[type-arg]
    return [
        r async for r in CsvConnector().fetch(SourceSpec(source=SourceType.JSON, json_path="x"))
    ]
