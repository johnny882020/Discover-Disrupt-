"""Model-ready dataset export."""

import io
import json
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from dndlabs.core.exceptions import ExportError
from dndlabs.core.schemas import CompoundProfile, ExportFormat, NormalizedRecord

#: Computed properties exported after the record fields (empty when unknown).
PROPERTY_COLUMNS: tuple[str, ...] = (
    "clogp", "tpsa", "hbd", "hba", "rotatable_bonds", "rings", "qed",
    "lipinski_violations", "potency_class",
)  # fmt: skip

#: Column order of exported files (stable contract for downstream models).
EXPORT_COLUMNS: tuple[str, ...] = (*NormalizedRecord.model_fields, *PROPERTY_COLUMNS)


class DatasetExporter:
    """Renders normalized records as CSV or JSON Lines with a fixed column order."""

    def export(
        self,
        records: Iterable[NormalizedRecord],
        fmt: ExportFormat,
        profiles: Mapping[uuid.UUID, CompoundProfile] | None = None,
    ) -> bytes:
        """Render records with their computed properties.

        Args:
            records: Records to export, in export order.
            fmt: Output format.
            profiles: Computed properties by record id; missing ones export empty.

        Returns:
            The serialized bytes.

        Raises:
            ExportError: If the requested format is unsupported.
        """
        rows = [_row(r, (profiles or {}).get(r.id)) for r in records]
        if fmt is ExportFormat.CSV:
            frame = pd.DataFrame(rows, columns=list(EXPORT_COLUMNS))
            return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        if fmt is ExportFormat.JSONL:
            buffer = io.StringIO()
            for row in rows:
                buffer.write(json.dumps(row, ensure_ascii=False))
                buffer.write("\n")
            return buffer.getvalue().encode("utf-8")
        raise ExportError(f"unsupported export format: {fmt}")  # pragma: no cover


def _row(record: NormalizedRecord, profile: CompoundProfile | None) -> dict[str, Any]:
    """One export row: the record's fields, then its properties, in column order."""
    properties = profile.model_dump(mode="json") if profile is not None else {}
    return {**record.model_dump(mode="json"), **{c: properties.get(c) for c in PROPERTY_COLUMNS}}
