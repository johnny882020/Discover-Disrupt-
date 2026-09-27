"""Uploaded files: store, preview with a suggested column mapping, and ingest.

An upload is stored once (per organization) and can be previewed and run any
number of times with different column mappings. The raw bytes are stored and
re-parsed on each use, so a run always reads the file as uploaded, with the
mapping chosen for that run.

Every read is scoped by ``org_id``: the upload's metadata is fetched with it
first, so another organization's upload id is a ``NotFoundError``, never data.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import MappingTemplateRepository, UploadRepository
from dndlabs.core.schemas import (
    MappingTemplate,
    MappingTemplateCreate,
    RawRecord,
    SourceSpec,
    SourceType,
    Upload,
    UploadPreview,
)
from dndlabs.ingestion.fields import build_mapped_record
from dndlabs.ingestion.mapping import suggest_mapping
from dndlabs.ingestion.tabular import Table, read_table, upload_format

logger = get_logger(__name__)

#: Rows returned in an upload preview.
PREVIEW_ROWS = 20


@dataclass(frozen=True)
class UploadLimits:
    """Size limits for uploaded files.

    Attributes:
        max_bytes: Largest accepted file.
        max_rows: Most data rows accepted in one file.
    """

    max_bytes: int = 25 * 1024 * 1024
    max_rows: int = 100_000


class UploadService:
    """Stores uploaded files and prepares them for a run."""

    def __init__(
        self,
        uploads: UploadRepository,
        templates: MappingTemplateRepository,
        limits: UploadLimits | None = None,
    ) -> None:
        """Create the service.

        Args:
            uploads: Upload repository.
            templates: Mapping-template repository.
            limits: Size limits; defaults to :class:`UploadLimits`.
        """
        self._uploads = uploads
        self._templates = templates
        self.limits = limits or UploadLimits()

    def store(self, org_id: uuid.UUID, filename: str, data: bytes) -> UploadPreview:
        """Validate, parse and store an uploaded file, and preview it.

        The file is parsed before it is stored, so an unreadable file is
        rejected immediately rather than when a run uses it.

        Args:
            org_id: The uploading organization.
            filename: The client's file name (determines the format).
            data: The file content.

        Returns:
            The stored upload's preview and suggested column mapping.

        Raises:
            IngestionError: If the file is empty, too large, of an
                unsupported type, or cannot be parsed.
        """
        if not data:
            raise IngestionError("the file is empty")
        if len(data) > self.limits.max_bytes:
            raise IngestionError(
                f"the file is {len(data)} bytes; the limit is {self.limits.max_bytes}"
            )
        fmt = upload_format(filename)
        table = read_table(data, fmt, self.limits.max_rows)
        upload = self._uploads.create(
            Upload(
                org_id=org_id,
                filename=filename[:255],  # the column is String(255)
                format=fmt,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            ),
            data,
        )
        logger.info(
            "upload_stored",
            extra={"upload_id": str(upload.id), "format": fmt.value, "rows": len(table.rows)},
        )
        return self._preview(upload, table)

    def preview(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> UploadPreview:
        """Preview a stored upload with a suggested column mapping.

        Args:
            org_id: Owning organization (enforced).
            upload_id: The upload.

        Returns:
            The preview.

        Raises:
            NotFoundError: If the upload does not exist in this org.
        """
        upload = self._uploads.get(org_id, upload_id)
        table = read_table(
            self._uploads.get_data(org_id, upload_id), upload.format, self.limits.max_rows
        )
        return self._preview(upload, table)

    def save_template(self, org_id: uuid.UUID, request: MappingTemplateCreate) -> MappingTemplate:
        """Save a column mapping for reuse (replacing a same-named one).

        Args:
            org_id: Owning organization.
            request: Name and mapping.

        Returns:
            The saved template.
        """
        return self._templates.create(
            MappingTemplate(org_id=org_id, name=request.name.strip(), mapping=request.mapping)
        )

    def list_templates(self, org_id: uuid.UUID) -> list[MappingTemplate]:
        """List an organization's saved column mappings.

        Args:
            org_id: Owning organization.

        Returns:
            The templates, by name.
        """
        return self._templates.list_templates(org_id)

    def delete_template(self, org_id: uuid.UUID, template_id: uuid.UUID) -> None:
        """Delete a saved column mapping.

        Args:
            org_id: Owning organization (enforced).
            template_id: The template.

        Raises:
            NotFoundError: If the template does not exist in this org.
        """
        self._templates.delete(org_id, template_id)

    def _preview(self, upload: Upload, table: Table) -> UploadPreview:
        """Build the preview of a parsed upload."""
        mapping, template = suggest_mapping(table, self._templates.list_templates(upload.org_id))
        return UploadPreview(
            upload=upload,
            columns=table.columns,
            rows=table.rows[:PREVIEW_ROWS],
            row_count=len(table.rows),
            suggested_mapping=mapping,
            template=template,
        )


class UploadConnector:
    """Reads an organization's uploaded file, applying the run's column mapping.

    Attributes:
        source: Always :attr:`SourceType.UPLOAD`.
    """

    source = SourceType.UPLOAD

    def __init__(self, uploads: UploadRepository, limits: UploadLimits | None = None) -> None:
        """Create the connector.

        Args:
            uploads: Upload repository.
            limits: Size limits; defaults to :class:`UploadLimits`.
        """
        self._uploads = uploads
        self._limits = limits or UploadLimits()

    async def fetch_for_org(self, org_id: uuid.UUID, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Yield one raw record per row of the uploaded file.

        Args:
            org_id: The organization running the pipeline (enforced).
            spec: An upload spec with ``upload_id`` and ``column_mapping``.

        Yields:
            Raw records; the id falls back to ``row-<n>`` when no column is
            mapped to ``source_record_id``.

        Raises:
            IngestionError: If the spec is not an upload spec, or maps a
                column the file does not have.
            NotFoundError: If the upload does not exist in this org.
        """
        if (
            spec.source is not SourceType.UPLOAD
            or spec.upload_id is None
            or not spec.column_mapping
        ):
            raise IngestionError("UploadConnector requires an upload spec with a column mapping")
        upload = self._uploads.get(org_id, spec.upload_id)
        table = read_table(
            self._uploads.get_data(org_id, spec.upload_id), upload.format, self._limits.max_rows
        )
        missing = sorted(set(spec.column_mapping) - set(table.columns))
        if missing:
            raise IngestionError(f"{upload.filename} has no column(s) {missing}")
        for index, row in enumerate(table.rows):
            yield build_mapped_record(
                SourceType.UPLOAD, row, spec.column_mapping, fallback_id=f"row-{index + 1}"
            )
        logger.info("upload read", extra={"upload_id": str(upload.id), "records": len(table.rows)})
