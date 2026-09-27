import uuid
from collections.abc import Sequence

import pytest

from dndlabs.core.exceptions import RunInterruptedError
from dndlabs.core.schemas import EnrichmentRequest, EnrichmentResult, NormalizedRecord, SourceType
from dndlabs.enrichment.null_client import NullEnrichmentClient
from dndlabs.enrichment.service import EnrichmentService

DATASET_ID = uuid.uuid4()


def _record(smiles: str | None) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id=DATASET_ID, source=SourceType.CSV, source_record_id="1", canonical_smiles=smiles
    )


async def test_defaults_to_null_client() -> None:
    service = EnrichmentService()
    assert service.is_enabled() is False
    [result] = await service.enrich([_record("CCO")])
    assert result.status == "skipped_no_key"


async def test_records_without_smiles_are_skipped_entirely() -> None:
    service = EnrichmentService()
    assert await service.enrich([_record(None)]) == []


async def test_empty_input_returns_empty() -> None:
    assert await EnrichmentService().enrich([]) == []


async def test_uses_provided_client() -> None:
    class AlwaysEnabled(NullEnrichmentClient):
        def is_enabled(self) -> bool:
            return True

    service = EnrichmentService(AlwaysEnabled())
    assert service.is_enabled() is True


class CountingClient:
    """An enabled client that enriches every record but the ones named ``fail``."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def is_enabled(self) -> bool:
        return True

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        self.batches.append(len(requests))
        return [
            EnrichmentResult(record_id=r.record_id, status="failed", error="bad")
            if r.smiles == "fail"
            else EnrichmentResult(record_id=r.record_id, status="enriched")
            for r in requests
        ]


async def test_a_real_client_is_called_in_batches_with_a_checkpoint_between() -> None:
    client = CountingClient()
    reported: list[int] = []
    records = [_record("fail" if i == 0 else "CCO") for i in range(5)]
    results = await EnrichmentService(client, batch_size=2).enrich(records, reported.append)
    assert client.batches == [2, 2, 1]
    assert reported == [1, 3]  # records enriched so far; a failed call is not counted
    assert [r.record_id for r in results] == [r.id for r in records]
    assert results[0].status == "failed"  # reported, never raised


async def test_what_the_checkpoint_raises_stops_enrichment() -> None:
    client = CountingClient()

    def stop(done: int) -> None:
        raise RunInterruptedError("shutting down")

    with pytest.raises(RunInterruptedError):
        await EnrichmentService(client, batch_size=2).enrich([_record("CCO")] * 5, stop)
    assert client.batches == [2]


async def test_the_null_client_takes_one_batch_without_checkpoints() -> None:
    reported: list[int] = []
    results = await EnrichmentService(batch_size=2).enrich(
        [_record("CCO") for _ in range(5)], reported.append
    )
    assert len(results) == 5 and reported == []
