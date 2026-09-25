"""Dataset and quality-report endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from dndlabs.api.dependencies import ApiServices, get_services
from dndlabs.core.schemas import Dataset, DatasetWithRecords, ExportFormat, QualityReport

router = APIRouter(prefix="/datasets", tags=["datasets"])

Services = Annotated[ApiServices, Depends(get_services)]

_MEDIA_TYPES = {ExportFormat.CSV: "text/csv", ExportFormat.JSONL: "application/x-ndjson"}


@router.get("")
def list_datasets(services: Services) -> list[Dataset]:
    """List datasets, newest first.

    Args:
        services: Injected services.

    Returns:
        Dataset metadata.
    """
    return services.repositories.datasets.list()


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str, services: Services) -> DatasetWithRecords:
    """Return a dataset with its normalized records.

    Args:
        dataset_id: Dataset identifier.
        services: Injected services.

    Returns:
        The dataset and records.
    """
    return services.repositories.datasets.get(dataset_id)


@router.get("/{dataset_id}/quality-report")
def get_quality_report(dataset_id: str, services: Services) -> QualityReport:
    """Return the quality report of a dataset.

    Args:
        dataset_id: Dataset identifier.
        services: Injected services.

    Returns:
        The quality report.
    """
    return services.repositories.reports.get_for_dataset(dataset_id)


@router.get("/{dataset_id}/export", response_class=PlainTextResponse)
def export_dataset(
    dataset_id: str,
    services: Services,
    fmt: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> PlainTextResponse:
    """Download a dataset in a model-ready format.

    Args:
        dataset_id: Dataset identifier.
        services: Injected services.
        fmt: ``csv`` or ``jsonl``.

    Returns:
        The serialized dataset as an attachment.
    """
    dataset = services.repositories.datasets.get(dataset_id)
    return PlainTextResponse(
        services.renderer.render(dataset, fmt),
        media_type=_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.{fmt.value}"'},
    )
