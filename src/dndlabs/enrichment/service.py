"""Selects the right enrichment client and applies it to a batch of records."""

from collections.abc import Sequence

from dndlabs.core.protocols import EnrichmentClient
from dndlabs.core.schemas import EnrichmentRequest, EnrichmentResult, NormalizedRecord
from dndlabs.enrichment.null_client import NullEnrichmentClient


class EnrichmentService:
    """Wraps an :class:`EnrichmentClient`, translating records to requests."""

    def __init__(self, client: EnrichmentClient | None = None) -> None:
        """Configure the service.

        Args:
            client: The enrichment client to use; defaults to a no-op client
                that marks every record ``skipped_no_key``.
        """
        self._client = client or NullEnrichmentClient()

    def is_enabled(self) -> bool:
        """Whether real enrichment calls will be made.

        Returns:
            True if a real (non-null) client is configured.
        """
        return self._client.is_enabled()

    async def enrich(self, records: Sequence[NormalizedRecord]) -> list[EnrichmentResult]:
        """Enrich a batch of accepted records.

        Only records with a canonical SMILES are submitted; others are
        reported unchanged as ``skipped_no_key`` is not applicable to them —
        callers should not expect a result for every input in that edge
        case, but in practice every accepted record has a canonical SMILES
        (the identity rule guarantees it).

        Args:
            records: Accepted, normalized records.

        Returns:
            One enrichment result per record with a canonical SMILES.
        """
        requests = [
            EnrichmentRequest(record_id=r.id, smiles=r.canonical_smiles)
            for r in records
            if r.canonical_smiles
        ]
        if not requests:
            return []
        return await self._client.enrich_batch(requests)
