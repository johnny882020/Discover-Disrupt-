import uuid

from dndlabs.core.schemas import NormalizedRecord, SourceType
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
