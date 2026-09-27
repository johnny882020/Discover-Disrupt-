"""Dataset, quality-report and export endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.schemas import (
    Dataset,
    DatasetAssessment,
    DatasetFilter,
    DatasetWithRecords,
    ExportFormat,
    NormalizedRecord,
    QualityReport,
    SourceType,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

_MEDIA_TYPES = {ExportFormat.CSV: "text/csv", ExportFormat.JSONL: "application/x-ndjson"}


@router.get("")
def list_datasets(org: CurrentOrg, services: Services) -> list[Dataset]:
    """List datasets for the calling organization, newest first.

    Args:
        org: The authenticated org context.
        services: Injected services.

    Returns:
        Dataset metadata.
    """
    return services.repositories.datasets.list_for_org(org.org_id)


@router.get("/{dataset_id}")
def get_dataset(dataset_id: uuid.UUID, org: CurrentOrg, services: Services) -> DatasetWithRecords:
    """Return a dataset with its normalized records.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The dataset and records.
    """
    return services.repositories.datasets.get(org.org_id, dataset_id)


@router.get("/{dataset_id}/records")
def filter_records(
    dataset_id: uuid.UUID,
    org: CurrentOrg,
    services: Services,
    mw_min: Annotated[float | None, Query()] = None,
    mw_max: Annotated[float | None, Query()] = None,
    target: Annotated[str | None, Query()] = None,
    source: Annotated[SourceType | None, Query()] = None,
    activity_min_nm: Annotated[float | None, Query()] = None,
    activity_max_nm: Annotated[float | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NormalizedRecord]:
    """Query a dataset's records with filters.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.
        mw_min: Minimum molecular weight.
        mw_max: Maximum molecular weight.
        target: Exact target match.
        source: Exact source match.
        activity_min_nm: Minimum activity value, in nM.
        activity_max_nm: Maximum activity value, in nM.
        limit: Page size.
        offset: Page offset.

    Returns:
        Matching records.
    """
    filters = DatasetFilter(
        mw_min=mw_min,
        mw_max=mw_max,
        target=target,
        source=source,
        activity_min_nm=activity_min_nm,
        activity_max_nm=activity_max_nm,
        limit=limit,
        offset=offset,
    )
    return services.repositories.datasets.filter_records(org.org_id, dataset_id, filters)


@router.get("/{dataset_id}/quality-report")
def get_quality_report(dataset_id: uuid.UUID, org: CurrentOrg, services: Services) -> QualityReport:
    """Return the quality report of a dataset.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The quality report.
    """
    return services.repositories.reports.get_for_dataset(org.org_id, dataset_id)


@router.get("/{dataset_id}/assessment")
def get_assessment(dataset_id: uuid.UUID, org: CurrentOrg, services: Services) -> DatasetAssessment:
    """Assess a dataset against hit-to-lead criteria.

    Potency classes from activity values (optimized < 100 nM, lead < 1 µM,
    hit < 10 µM); property criteria (MW, cLogP, Lipinski, rotatable bonds,
    polar surface area) over all compounds, the actives and the five most
    potent; and every compound's computed properties.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.

    Returns:
        The assessment.
    """
    return services.assessment.assess(org.org_id, dataset_id)


@router.get(
    "/{dataset_id}/export",
    response_class=Response,
    responses={
        200: {
            "description": "The dataset file, as an attachment.",
            "content": {media: {} for media in _MEDIA_TYPES.values()},
        }
    },
)
def export_dataset(
    dataset_id: uuid.UUID,
    org: CurrentOrg,
    services: Services,
    fmt: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    """Download a dataset in a model-ready format.

    Args:
        dataset_id: Dataset identifier.
        org: The authenticated org context.
        services: Injected services.
        fmt: ``csv`` or ``jsonl``.

    Returns:
        The serialized dataset as an attachment.
    """
    dataset = services.repositories.datasets.get(org.org_id, dataset_id)
    assessment = services.assessment.assess_records(org.org_id, dataset_id, dataset.records)
    profiles = {p.record_id: p for p in assessment.profiles}
    body = services.exporter.export(dataset.records, fmt, profiles)
    return Response(
        content=body,
        media_type=_MEDIA_TYPES[fmt],
        # Filename built only from the UUID and the enum value, never from
        # user-supplied text, so it cannot inject into the header.
        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.{fmt.value}"'},
    )
