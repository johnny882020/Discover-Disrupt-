"""Model-ready dataset export."""

import io
from collections.abc import Iterable

import pandas as pd

from dndlabs.core.exceptions import ExportError
from dndlabs.core.schemas import ExportFormat, NormalizedRecord

#: Column order of exported files (stable contract for downstream models).
EXPORT_COLUMNS: tuple[str, ...] = tuple(NormalizedRecord.model_fields)


class DatasetExporter:
    """Renders normalized records as CSV or JSON Lines with a fixed column order."""

    def export(self, records: Iterable[NormalizedRecord], fmt: ExportFormat) -> bytes:
        """Render records.

        Args:
            records: Records to export, in export order.
            fmt: Output format.

        Returns:
            The serialized bytes.

        Raises:
            ExportError: If the requested format is unsupported.
        """
        records = list(records)
        if fmt is ExportFormat.CSV:
            frame = pd.DataFrame(
                [r.model_dump(mode="json") for r in records], columns=list(EXPORT_COLUMNS)
            )
            return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        if fmt is ExportFormat.JSONL:
            buffer = io.StringIO()
            for record in records:
                buffer.write(record.model_dump_json())
                buffer.write("\n")
            return buffer.getvalue().encode("utf-8")
        raise ExportError(f"unsupported export format: {fmt}")  # pragma: no cover
