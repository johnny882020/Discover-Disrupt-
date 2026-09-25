from pathlib import Path

import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.csv_connector import CsvConnector
from tests.conftest import FIXTURES


def _fetch(path: Path) -> list:  # type: ignore[type-arg]
    return CsvConnector().fetch(SourceSpec(source=SourceType.CSV, path=str(path)))


def test_reads_malformed_fixture_verbatim() -> None:
    records = _fetch(FIXTURES / "lab_export_malformed.csv")
    assert len(records) == 12  # blank row skipped
    first = records[0]
    assert first.source_record_id == "LAB-001"
    assert first.activity_value == "1.5"
    assert first.activity_unit == "uM"
    assert first.extra == {"plate": "P1"}
    by_id = {r.source_record_id: r for r in records}
    assert by_id["LAB-007"].activity_value == "abc"
    assert by_id["LAB-008"].smiles is None
    assert by_id["LAB-009"].activity_unit is None
    assert by_id["LAB-004"].activity_unit == "µM"


def test_semicolon_delimiter_and_aliases(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("SMILES;Value;Units;Formula\nCCO;5;nM;C2H6O\n", encoding="utf-8")
    [record] = _fetch(path)
    assert record.smiles == "CCO"
    assert record.activity_value == "5"
    assert record.molecular_formula == "C2H6O"
    assert record.source_record_id == "row-1"


def test_missing_identifier_column(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text("name,value\nfoo,1\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="no identifier column"):
        _fetch(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="not found"):
        _fetch(tmp_path / "missing.csv")


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(IngestionError):
        _fetch(path)


def test_header_only_file(tmp_path: Path) -> None:
    path = tmp_path / "h.csv"
    path.write_text("smiles,name\n", encoding="utf-8")
    assert _fetch(path) == []


def test_ragged_rows_raise(tmp_path: Path) -> None:
    path = tmp_path / "r.csv"
    path.write_text("smiles,name\nCCO,a,extra,more\n", encoding="utf-8")
    with pytest.raises(IngestionError, match="cannot parse"):
        _fetch(path)


def test_rejects_wrong_spec() -> None:
    with pytest.raises(IngestionError):
        CsvConnector().fetch(SourceSpec(source=SourceType.JSON, path="x"))
