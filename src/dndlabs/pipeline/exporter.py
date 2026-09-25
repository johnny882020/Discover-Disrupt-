"""Model-ready dataset export."""

import io
from pathlib import Path

import pandas as pd

from dndlabs.core.exceptions import ExportError
from dndlabs.core.schemas import DatasetWithRecords, ExportFormat, NormalizedRecord

#: Column order of exported files (stable contract for downstream models).
EXPORT_COLUMNS: tuple[str, ...] = tuple(NormalizedRecord.model_fields)


class DatasetExporter:
    """Renders datasets as CSV or JSON Lines with a fixed column order."""

    def render(self, dataset: DatasetWithRecords, fmt: ExportFormat) -> str:
        """Render a dataset to text.

        Args:
            dataset: Dataset to render.
            fmt: Output format.

        Returns:
            The serialized dataset.
        """
        frame = pd.DataFrame(
            [r.model_dump(mode="json") for r in dataset.records], columns=list(EXPORT_COLUMNS)
        )
        if fmt is ExportFormat.CSV:
            return frame.to_csv(index=False, lineterminator="\n")
        buffer = io.StringIO()
        for record in dataset.records:
            buffer.write(record.model_dump_json())
            buffer.write("\n")
        return buffer.getvalue()

    def write(self, dataset: DatasetWithRecords, fmt: ExportFormat, directory: Path) -> Path:
        """Write a dataset to ``directory/<dataset_id>.<fmt>``.

        Args:
            dataset: Dataset to export.
            fmt: Output format.
            directory: Target directory (created if missing).

        Returns:
            Path of the written file.

        Raises:
            ExportError: If the file cannot be written.
        """
        path = directory / f"{dataset.dataset.id}.{fmt.value}"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path.write_text(self.render(dataset, fmt), encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"cannot write {path}: {exc}") from exc
        return path
