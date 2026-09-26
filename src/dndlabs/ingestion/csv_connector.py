"""CSV connector for lab-instrument / ELN exports."""

from collections.abc import AsyncIterator
from pathlib import Path

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import RawRecord, SourceSpec, SourceType
from dndlabs.ingestion.fields import IDENTIFIER_FIELDS, build_raw_record, canonical_field
from dndlabs.ingestion.tabular import Table, read_delimited

logger = get_logger(__name__)


class CsvConnector:
    """Reads compound rows from a delimited text file.

    Attributes:
        source: Always :attr:`SourceType.CSV`.
    """

    source = SourceType.CSV

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Read all non-empty rows of the file at ``spec.csv_path``.

        Args:
            spec: A CSV source spec.

        Yields:
            One raw record per non-empty row; the id falls back to
            ``row-<n>`` (1-based data row number) when no id column exists.

        Raises:
            IngestionError: If the file is missing, unparsable, or has no
                SMILES/InChI column.
        """
        if spec.source is not SourceType.CSV or spec.csv_path is None:
            raise IngestionError("CsvConnector requires a csv spec with csv_path")
        table = _read_table(Path(spec.csv_path))
        mapped = {canonical_field(c) for c in table.columns}
        if not mapped.intersection(IDENTIFIER_FIELDS):
            needed = ", ".join(IDENTIFIER_FIELDS)
            raise IngestionError(f"{spec.csv_path}: no identifier column (need one of {needed})")
        count = 0
        for index, row in enumerate(table.rows):
            yield build_raw_record(SourceType.CSV, row, fallback_id=f"row-{index + 1}")
            count += 1
        logger.info("csv read", extra={"path": spec.csv_path, "records": count})


def _read_table(path: Path) -> Table:
    """Load the file as a table of strings, dropping fully blank rows."""
    if not path.is_file():
        raise IngestionError(f"CSV file not found: {path}")
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestionError(f"cannot parse CSV {path}: {exc}") from exc
    try:
        return read_delimited(text)
    except IngestionError as exc:
        raise IngestionError(f"cannot parse CSV {path}: {exc}") from exc
