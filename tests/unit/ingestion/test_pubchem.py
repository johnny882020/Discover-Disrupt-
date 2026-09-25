import httpx
import pytest
from tests.conftest import FIXTURES

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.pubchem import PubChemConnector, build_pubchem_client

BASE = "https://pubchem.test/rest/pug"


def _fixture(name: str) -> bytes:
    return (FIXTURES / "pubchem" / name).read_bytes()


def _connector(handler: httpx.MockTransport, **kwargs: object) -> PubChemConnector:
    client = httpx.Client(base_url=BASE, transport=handler)
    sleeps: list[float] = []
    return PubChemConnector(client, sleep=sleeps.append, **kwargs)  # type: ignore[arg-type]


async def _fetch(connector: PubChemConnector, *cids: str) -> list:  # type: ignore[type-arg]
    spec = SourceSpec(source=SourceType.PUBCHEM, identifiers=list(cids))
    return [r async for r in connector.fetch(spec)]


async def test_fetch_parses_fixture() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=_fixture("properties_3.json"))

    records = await _fetch(_connector(httpx.MockTransport(handler)), "2244", "3672", "2519")
    assert len(records) == 3
    assert len(seen) == 1
    aspirin = records[0]
    assert aspirin.source_record_id == "2244"
    assert aspirin.name == "Aspirin"
    assert aspirin.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert aspirin.extra == {"pubchem_cid": 2244}


async def test_fetch_batches_and_dedupes_cids() -> None:
    import json

    paths: list[str] = []
    table = json.loads(_fixture("properties_3.json"))["PropertyTable"]["Properties"]
    by_cid = {str(p["CID"]): p for p in table}

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        cids = request.url.path.split("/cid/")[1].split("/")[0].split(",")
        return httpx.Response(
            200, json={"PropertyTable": {"Properties": [by_cid[c] for c in cids]}}
        )

    connector = _connector(httpx.MockTransport(handler), batch_size=2)
    records = await _fetch(connector, "2244", "3672", "2519", "2244")
    assert len(paths) == 2
    assert [r.source_record_id for r in records] == ["2244", "3672", "2519"]


async def test_retries_transient_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset")
        if calls["n"] == 2:
            return httpx.Response(503, json={"Fault": {"Code": "PUGREST.ServerBusy"}})
        return httpx.Response(200, content=_fixture("properties_3.json"))

    records = await _fetch(_connector(httpx.MockTransport(handler), max_retries=2), "2244")
    assert len(records) == 3
    assert calls["n"] == 3


async def test_gives_up_after_max_retries() -> None:
    def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"Fault": {"Message": "Server busy"}})

    with pytest.raises(IngestionError, match="Server busy"):
        await _fetch(_connector(httpx.MockTransport(busy), max_retries=1), "2244")


async def test_non_retryable_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Bad request")

    with pytest.raises(IngestionError, match="400"):
        await _fetch(_connector(httpx.MockTransport(handler)), "2244")


async def test_malformed_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(IngestionError, match="unexpected PubChem response"):
        await _fetch(_connector(httpx.MockTransport(handler)), "2244")


async def test_rejects_wrong_source() -> None:
    connector = _connector(httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(IngestionError):
        spec = SourceSpec(source=SourceType.CSV, csv_path="x.csv")
        [r async for r in connector.fetch(spec)]


def test_build_client() -> None:
    client = build_pubchem_client(BASE, 5)
    assert str(client.base_url).startswith(BASE)
    assert "dndlabs" in client.headers["User-Agent"]
