"""No-op enrichment client used when no NVIDIA API key is configured."""

from collections.abc import Sequence

from dndlabs.core.schemas import EnrichmentRequest, EnrichmentResult


class NullEnrichmentClient:
    """Reports every record as explicitly not enriched.

    "NVIDIA or nothing": there is no local classical fallback provider — when
    no API key is configured, enrichment is skipped and shown as such, never
    approximated.
    """

    def is_enabled(self) -> bool:
        """Whether this client can make real calls.

        Returns:
            Always False.
        """
        return False

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        """Return a ``skipped_no_key`` result for every request.

        Args:
            requests: Records that would have been enriched.

        Returns:
            One ``skipped_no_key`` result per request.
        """
        return [EnrichmentResult(record_id=r.record_id, status="skipped_no_key") for r in requests]
