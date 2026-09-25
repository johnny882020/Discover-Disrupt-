import json
from pathlib import Path

import httpx
import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import IdentifierType, SourceSpec, SourceType
from dndlabs.ingestion.pubchem import PubChemConnector, PubChemProperties, build_pubchem_client
from tests.conftest import FIXTURES, PUBCHEM_12_CIDS

BASE = "https://pubchem.test/rest/pug"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _connector(handler: httpx.MockTransport, **kwargs: object) -> PubChemConnector:
    client = httpx.Client(base_url=BASE, transport=handler)
    sleeps: list[float] = []
    return PubChemConnector(client, sleep=sleeps.append, **kwargs)  # type: ignore[arg-type]


def _cid_spec(*cids: str) -> SourceSpec:
    return SourceSpec(source=SourceType.PUBCHEM, identifiers=list(cids))


def test_fetch_cids_parses_fixture() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=_fixture("pubchem_properties_12.json"))

    records = _connector(httpx.MockTransport(handler)).fetch(_cid_spec(*PUBCHEM_12_CIDS))
    assert len(records) == 12
    assert len(seen) == 1
    assert "/compound/cid/2244,3672" in seen[0]
    aspirin = records[0]
    assert aspirin.source is SourceType.PUBCHEM
    assert aspirin.source_record_id == "2244"
    assert aspirin.name == "Aspirin"
    assert aspirin.smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
    assert aspirin.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
    assert aspirin.molecular_weight == "180.16"
    assert aspirin.extra == {"pubchem_cid": 2244}


def test_fetch_batches_and_dedupes_cids() -> None:
    paths: list[str] = []
    table = json.loads(_fixture("pubchem_properties_12.json"))["PropertyTable"]["Properties"]
    by_cid = {str(p["CID"]): p for p in table}

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        cids = request.url.path.split("/cid/")[1].split("/")[0].split(",")
        body = {"PropertyTable": {"Properties": [by_cid[c] for c in cids]}}
        return httpx.Response(200, json=body)

    connector = _connector(httpx.MockTransport(handler), batch_size=5)
    records = connector.fetch(_cid_spec(*PUBCHEM_12_CIDS, "2244"))
    assert len(paths) == 3
    assert [r.source_record_id for r in records] == PUBCHEM_12_CIDS


def test_legacy_smiles_keys_supported() -> None:
    legacy = PubChemProperties.model_validate(
        {"CID": 1, "CanonicalSMILES": "CCO", "IsomericSMILES": "C[C@H](N)O"}
    )
    assert legacy.best_smiles() == "C[C@H](N)O"
    assert PubChemProperties.model_validate({"CID": 1, "ConnectivitySMILES": "CC"}).best_smiles()


def test_fetch_by_name_handles_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "aspirin" in request.url.path:
            return httpx.Response(200, content=_fixture("pubchem_name_aspirin.json"))
        return httpx.Response(404, content=_fixture("pubchem_not_found.json"))

    spec = SourceSpec(
        source=SourceType.PUBCHEM,
        identifiers=["aspirin", "not a drug"],
        identifier_type=IdentifierType.NAME,
    )
    records = _connector(httpx.MockTransport(handler)).fetch(spec)
    assert [r.name for r in records] == ["Aspirin"]


def test_retries_transient_errors_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset")
        if calls["n"] == 2:
            return httpx.Response(503, json={"Fault": {"Code": "PUGREST.ServerBusy"}})
        return httpx.Response(200, content=_fixture("pubchem_name_aspirin.json"))

    records = _connector(httpx.MockTransport(handler), max_retries=2).fetch(_cid_spec("2244"))
    assert len(records) == 1
    assert calls["n"] == 3


def test_gives_up_after_max_retries() -> None:
    def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"Fault": {"Message": "Server busy"}})

    with pytest.raises(IngestionError, match="Server busy"):
        _connector(httpx.MockTransport(busy), max_retries=1).fetch(_cid_spec("2244"))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(IngestionError, match="unreachable"):
        _connector(httpx.MockTransport(down), max_retries=1).fetch(_cid_spec("2244"))


def test_non_retryable_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Bad request")

    with pytest.raises(IngestionError, match="400"):
        _connector(httpx.MockTransport(handler)).fetch(_cid_spec("2244"))


def test_malformed_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(IngestionError, match="unexpected PubChem response"):
        _connector(httpx.MockTransport(handler)).fetch(_cid_spec("2244"))


def test_rejects_wrong_source() -> None:
    connector = _connector(httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(IngestionError):
        connector.fetch(SourceSpec(source=SourceType.CSV, path="x.csv"))


def test_build_client(tmp_path: Path) -> None:
    client = build_pubchem_client(BASE, 5)
    assert str(client.base_url).startswith(BASE)
    assert "dndlabs" in client.headers["User-Agent"]
