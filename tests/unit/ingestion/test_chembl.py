import httpx
import pytest
from tests.conftest import FIXTURES

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.chembl import ChemblConnector, build_chembl_client

BASE = "https://chembl.test/chembl/api/data"


def _fixture(name: str) -> bytes:
    return (FIXTURES / "chembl" / name).read_bytes()


async def _fetch(connector: ChemblConnector, target: str = "CHEMBL204") -> list:  # type: ignore[type-arg]
    spec = SourceSpec(source=SourceType.CHEMBL, chembl_target=target)
    return [r async for r in connector.fetch(spec)]


async def test_fetch_paginates_across_both_pages() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path + "?" + (request.url.query.decode() or ""))
        if "offset=2" in request.url.query.decode():
            return httpx.Response(200, content=_fixture("activity_page2.json"))
        return httpx.Response(200, content=_fixture("activity_page1.json"))

    connector = ChemblConnector(httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler)))
    records = await _fetch(connector)
    assert len(paths) == 2
    assert [r.source_record_id for r in records] == ["CHEMBL25", "CHEMBL521", "CHEMBL113"]
    aspirin = records[0]
    assert aspirin.activity_value == "1500"
    assert aspirin.activity_unit == "nM"
    assert aspirin.target == "CHEMBL204"


async def test_next_link_prefix_is_stripped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chembl/api/data/activity.json":
            return httpx.Response(200, content=_fixture("activity_page2.json"))
        return httpx.Response(404)

    connector = ChemblConnector(httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler)))
    records = await _fetch(connector)
    assert len(records) == 1


async def test_rejects_wrong_source() -> None:
    connector = ChemblConnector(
        httpx.Client(base_url=BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    )
    with pytest.raises(IngestionError):
        spec = SourceSpec(source=SourceType.CSV, csv_path="x")
        [r async for r in connector.fetch(spec)]


async def test_server_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    connector = ChemblConnector(httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler)))
    with pytest.raises(IngestionError, match="400"):
        await _fetch(connector)


def test_build_client() -> None:
    client = build_chembl_client(BASE, 5)
    assert str(client.base_url).startswith(BASE)
