"""Uploaded files and saved column mappings."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status
from starlette.concurrency import run_in_threadpool

from dndlabs.api.dependencies import CurrentOrg, Services
from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import MappingTemplate, MappingTemplateCreate, UploadPreview

router = APIRouter(tags=["uploads"])


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: Annotated[UploadFile, File(description="CSV, TSV, XLSX, SDF, SMILES or MOL file.")],
    org: CurrentOrg,
    services: Services,
) -> UploadPreview:
    """Upload a file for ingestion and preview it with a suggested column mapping.

    Start a run with ``{"source": "upload", "upload_id": …, "column_mapping": …}``.

    Args:
        file: The file (multipart field ``file``).
        org: The authenticated context.
        services: Injected services.

    Returns:
        The stored upload, its columns, first rows, row count and suggested
        column mapping (from a saved template when one matches its headers).

    Raises:
        IngestionError: If the file is too large, unsupported or unreadable (422).
    """
    limit = services.uploads.limits.max_bytes
    # Read at most one byte past the limit: enough to detect an oversized
    # file without reading all of it into memory.
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise IngestionError(f"the file is larger than the {limit}-byte limit")
    # Parsing (up to the size limit) and storing are blocking; off the event
    # loop they don't stall other requests or the in-process run worker.
    return await run_in_threadpool(
        services.uploads.store, org.org_id, file.filename or "upload", data
    )


@router.get("/uploads/{upload_id}/preview")
def preview_upload(upload_id: uuid.UUID, org: CurrentOrg, services: Services) -> UploadPreview:
    """Preview a previously uploaded file with a suggested column mapping.

    Args:
        upload_id: The upload.
        org: The authenticated context.
        services: Injected services.

    Returns:
        The preview.
    """
    return services.uploads.preview(org.org_id, upload_id)


@router.get("/mapping-templates")
def list_templates(org: CurrentOrg, services: Services) -> list[MappingTemplate]:
    """List the organization's saved column mappings.

    Args:
        org: The authenticated context.
        services: Injected services.

    Returns:
        The templates, by name.
    """
    return services.uploads.list_templates(org.org_id)


@router.post("/mapping-templates", status_code=status.HTTP_201_CREATED)
def save_template(
    body: MappingTemplateCreate, org: CurrentOrg, services: Services
) -> MappingTemplate:
    """Save a column mapping; uploads whose headers include its columns get it suggested.

    A template with the same name is replaced.

    Args:
        body: Name and mapping.
        org: The authenticated context.
        services: Injected services.

    Returns:
        The saved template.
    """
    return services.uploads.save_template(org.org_id, body)


@router.delete("/mapping-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: uuid.UUID, org: CurrentOrg, services: Services) -> None:
    """Delete a saved column mapping.

    Args:
        template_id: The template.
        org: The authenticated context.
        services: Injected services.
    """
    services.uploads.delete_template(org.org_id, template_id)
