import httpx
import pytest
from tests.conftest import FIXTURES

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.chembl import ChemblConnector, build_chembl_client

BASE = "https://chembl.test/chembl/api/data"


def _fixture(name: str) -> bytes:
    return (FIXTURES / "chembl" / name).read_bytes()


def _connector(handler: httpx.MockTransport, **kwargs: object) -> ChemblConnector:
    client = httpx.Client(base_url=BASE, transport=handler)
    sleeps: list[float] = []
    return ChemblConnector(client, sleep=sleeps.append, **kwargs)  # type: ignore[arg-type]


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


async def test_retries_transport_error_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset")
        return httpx.Response(200, content=_fixture("activity_page2.json"))

    connector = _connector(httpx.MockTransport(handler), max_retries=2)
    records = await _fetch(connector)
    assert calls["n"] == 2
    assert len(records) == 1


async def test_retries_retryable_status_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="server busy")
        return httpx.Response(200, content=_fixture("activity_page2.json"))

    connector = _connector(httpx.MockTransport(handler), max_retries=2)
    records = await _fetch(connector)
    assert calls["n"] == 2
    assert len(records) == 1


async def test_backoff_sleeps_between_retries_with_doubling_delay() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="server busy")

    client = httpx.Client(base_url=BASE, transport=httpx.MockTransport(handler))
    connector = ChemblConnector(client, max_retries=2, backoff_seconds=0.1, sleep=sleeps.append)
    with pytest.raises(IngestionError):
        await _fetch(connector)
    assert sleeps == [0.1, 0.2]


async def test_transport_error_exhausts_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("still down")

    connector = _connector(httpx.MockTransport(handler), max_retries=1)
    with pytest.raises(IngestionError, match="ChEMBL unreachable"):
        await _fetch(connector)


async def test_malformed_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    connector = _connector(httpx.MockTransport(handler))
    with pytest.raises(IngestionError, match="unexpected ChEMBL response"):
        await _fetch(connector)


def test_build_client() -> None:
    client = build_chembl_client(BASE, 5)
    assert str(client.base_url).startswith(BASE)
