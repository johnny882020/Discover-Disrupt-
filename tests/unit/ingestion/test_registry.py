import pytest

from dndlabs.core.exceptions import ConnectorNotFoundError
from dndlabs.core.schemas import SourceType
from dndlabs.ingestion.csv_connector import CsvConnector
from dndlabs.ingestion.json_connector import JsonConnector
from dndlabs.ingestion.registry import ConnectorRegistry


def test_lookup_by_enum_and_string() -> None:
    csv, js = CsvConnector(), JsonConnector()
    registry = ConnectorRegistry([csv, js])
    assert registry.get(SourceType.CSV) is csv
    assert registry.get("JSON") is js
    assert set(registry.sources) == {SourceType.CSV, SourceType.JSON}


def test_planned_and_unknown_sources() -> None:
    registry = ConnectorRegistry([])
    with pytest.raises(ConnectorNotFoundError, match="planned"):
        registry.get("uniprot")
    with pytest.raises(ConnectorNotFoundError, match="no connector"):
        registry.get("pubchem")
