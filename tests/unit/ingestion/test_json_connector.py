from pathlib import Path

import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.json_connector import JsonConnector


async def _fetch(path: Path) -> list:  # type: ignore[type-arg]
    return [
        r
        async for r in JsonConnector().fetch(
            SourceSpec(source=SourceType.JSON, json_path=str(path))
        )
    ]


async def test_reads_top_level_list(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('[{"smiles": "CCO", "flag": true}]', encoding="utf-8")
    [record] = await _fetch(path)
    assert record.smiles == "CCO"
    assert record.extra == {"flag": True}


async def test_reads_envelope(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text('{"records": [{"id": "DL-1", "smiles": "CC"}]}', encoding="utf-8")
    [record] = await _fetch(path)
    assert record.source_record_id == "DL-1"


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("{not json", "invalid JSON"),
        ('{"rows": []}', "expected a list"),
        ('[{"smiles": {"nested": 1}}]', "expected a list"),
    ],
)
async def test_malformed_documents(tmp_path: Path, content: str, match: str) -> None:
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(IngestionError, match=match):
        await _fetch(path)


async def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(IngestionError, match="not found"):
        await _fetch(tmp_path / "nope.json")
