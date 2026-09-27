"""Selects the right enrichment client and applies it to a run's accepted records.

With a real client every record is one GenMol call (up to a minute each), so
a large dataset can enrich for hours. Records are therefore sent in small
batches, and between batches the caller's ``checkpoint`` reports progress and
may stop the run (a cancellation, a shutdown).
"""

from collections.abc import Callable, Sequence

from dndlabs.core.protocols import EnrichmentClient
from dndlabs.core.schemas import EnrichmentRequest, EnrichmentResult, NormalizedRecord
from dndlabs.enrichment.null_client import NullEnrichmentClient

#: Records per batch between checkpoints with a real client: a stop request
#: waits for at most this many calls, while progress is written only once
#: per batch.
DEFAULT_BATCH_SIZE = 10


class EnrichmentService:
    """Wraps an :class:`EnrichmentClient`, translating records to requests."""

    def __init__(
        self, client: EnrichmentClient | None = None, batch_size: int = DEFAULT_BATCH_SIZE
    ) -> None:
        """Configure the service.

        Args:
            client: The enrichment client to use; defaults to a no-op client
                that marks every record ``skipped_no_key``.
            batch_size: Records sent per batch with a real client.
        """
        self._client = client or NullEnrichmentClient()
        self._batch_size = max(1, batch_size)

    def is_enabled(self) -> bool:
        """Whether real enrichment calls will be made.

        Returns:
            True if a real (non-null) client is configured.
        """
        return self._client.is_enabled()

    async def enrich(
        self,
        records: Sequence[NormalizedRecord],
        checkpoint: Callable[[int], None] | None = None,
    ) -> list[EnrichmentResult]:
        """Enrich a run's accepted records.

        Only records with a canonical SMILES are submitted; in practice every
        accepted record has one (the identity rule guarantees it). A failed
        call is a ``status="failed"`` result from the client, never raised.

        Args:
            records: Accepted, normalized records.
            checkpoint: Called between batches with the number of records
                enriched so far (``status="enriched"``); whatever it raises
                propagates and stops enrichment.

        Returns:
            One enrichment result per record with a canonical SMILES, in order.
        """
        requests = [
            EnrichmentRequest(record_id=r.id, smiles=r.canonical_smiles)
            for r in records
            if r.canonical_smiles
        ]
        if not requests:
            return []
        # The null client makes no calls: nothing to wait for, so one batch
        # and no progress writes, however large the dataset.
        size = self._batch_size if self._client.is_enabled() else len(requests)
        results: list[EnrichmentResult] = []
        for start in range(0, len(requests), size):
            if start and checkpoint is not None:
                checkpoint(sum(1 for r in results if r.status == "enriched"))
            results.extend(await self._client.enrich_batch(requests[start : start + size]))
        return results
