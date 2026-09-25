import uuid

from dndlabs.core.schemas import EnrichmentRequest
from dndlabs.enrichment.null_client import NullEnrichmentClient


async def test_null_client_skips_everything() -> None:
    client = NullEnrichmentClient()
    assert client.is_enabled() is False
    requests = [EnrichmentRequest(record_id=uuid.uuid4(), smiles="CCO") for _ in range(3)]
    results = await client.enrich_batch(requests)
    assert all(r.status == "skipped_no_key" for r in results)
    assert len(results) == 3
