import uuid

import httpx
from tests.conftest import FIXTURES

from dndlabs.core.schemas import EnrichmentRequest
from dndlabs.enrichment.client import HttpGenMolClient, build_nim_client

RECORD_ID = uuid.uuid4()


def _client(handler: httpx.MockTransport) -> HttpGenMolClient:
    http = httpx.Client(base_url="https://nim.test", transport=handler)
    return HttpGenMolClient(http, num_candidates=3, scoring="QED")


async def test_enrich_batch_parses_fixture() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["path"] = request.url.path
        return httpx.Response(
            200, content=(FIXTURES / "genmol" / "generate_response.json").read_bytes()
        )

    client = _client(httpx.MockTransport(handler))
    assert client.is_enabled() is True
    [result] = await client.enrich_batch([EnrichmentRequest(record_id=RECORD_ID, smiles="CCO")])
    assert result.status == "enriched"
    assert result.model_id == "genmol"
    assert len(result.candidates) == 3
    assert result.candidates[0].scoring_method == "QED"
    assert seen["path"] == "/generate"
    import json

    body = json.loads(seen["body"])
    assert body == {
        "smiles": "CCO",
        "num_molecules": 3,
        "temperature": 1,
        "noise": 0.2,
        "step_size": 4,
        "scoring": "QED",
    }


async def test_enrich_batch_handles_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    client = _client(httpx.MockTransport(handler))
    [result] = await client.enrich_batch([EnrichmentRequest(record_id=RECORD_ID, smiles="CCO")])
    assert result.status == "failed"
    assert result.error is not None


async def test_enrich_batch_handles_malformed_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    client = _client(httpx.MockTransport(handler))
    [result] = await client.enrich_batch([EnrichmentRequest(record_id=RECORD_ID, smiles="CCO")])
    assert result.status == "failed"


async def test_enrich_batch_one_failure_does_not_affect_others() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(
            200, content=(FIXTURES / "genmol" / "generate_response.json").read_bytes()
        )

    client = _client(httpx.MockTransport(handler))
    results = await client.enrich_batch(
        [
            EnrichmentRequest(record_id=uuid.uuid4(), smiles="CCO"),
            EnrichmentRequest(record_id=uuid.uuid4(), smiles="CCN"),
        ]
    )
    assert [r.status for r in results] == ["failed", "enriched"]


def test_build_nim_client_sets_auth_header() -> None:
    client = build_nim_client("https://nim.test", "secret-key", 10)
    assert client.headers["Authorization"] == "Bearer secret-key"
