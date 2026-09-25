"""Enrichment result endpoints."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.schemas import EnrichmentResult

router = APIRouter(prefix="/datasets", tags=["enrichment"])


class EnrichmentResponse(BaseModel):
    """Enrichment results for a dataset, plus whether the feature is live."""

    enrichment_enabled: bool
    results: list[EnrichmentResult]


@router.get("/{dataset_id}/enrichment")
def get_enrichment(
    dataset_id: uuid.UUID, org: CurrentOrg, services: Services
) -> EnrichmentResponse:
    """Return enrichment results for every record in a dataset.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The results, plus whether NVIDIA enrichment is currently configured
        (so the UI can distinguish "not enriched yet" from "enrichment is
        off — no NVIDIA API key configured").
    """
    results = services.repositories.enrichments.get_for_dataset(org.org_id, dataset_id)
    return EnrichmentResponse(
        enrichment_enabled=services.service.enrichment_enabled(), results=results
    )
