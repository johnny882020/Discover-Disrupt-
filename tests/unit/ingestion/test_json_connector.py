from pathlib import Path

import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.json_connector import JsonConnector
from tests.conftest import FIXTURES


def _fetch(path: Path) -> list:  # type: ignore[type-arg]
    return JsonConnector().fetch(SourceSpec(source=SourceType.JSON, path=str(path)))


def test_reads_envelope_fixture() -> None:
    records = _fetch(FIXTURES / "data_lake_upload.json")
    assert [r.source_record_id for r in records] == ["DL-1", "DL-2", "DL-3", "item-4"]
    first = records[0]
    assert first.name == "Aspirin"
    assert first.activity_value == 3.2
    assert first.activity_type == "IC50"
    assert first.extra == {"batch": 7}
    assert records[1].inchi is not None
    assert records[1].activity_value == 40.0


def test_reads_top_level_list(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('[{"smiles": "CCO", "flag": true}]', encoding="utf-8")
    [record] = _fetch(path)
    assert record.smiles == "CCO"
    assert record.extra == {"flag": True}


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("{not json", "invalid JSON"),
        ('{"rows": []}', "expected a list"),
        ('[{"smiles": {"nested": 1}}]', "expected a list"),
        ('"just a string"', "expected a list"),
    ],
)
def test_malformed_documents(tmp_path: Path, content: str, match: str) -> None:
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(IngestionError, match=match):
        _fetch(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="not found"):
        _fetch(tmp_path / "nope.json")


def test_rejects_wrong_spec() -> None:
    with pytest.raises(IngestionError):
        JsonConnector().fetch(SourceSpec(source=SourceType.CSV, path="x"))
