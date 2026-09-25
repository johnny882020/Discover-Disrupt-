"""CSV connector for lab-instrument / ELN exports."""

import csv
import warnings
from pathlib import Path

import pandas as pd

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import JsonScalar, RawRecord, SourceSpec, SourceType
from dndlabs.ingestion.fields import IDENTIFIER_FIELDS, build_raw_record, canonical_field

logger = get_logger(__name__)


class CsvConnector:
    """Reads compound rows from a delimited text file.

    All cells are read as strings so malformed values reach validation
    unchanged. The delimiter is sniffed (comma, semicolon, tab).

    Attributes:
        source: Always :attr:`SourceType.CSV`.
    """

    source = SourceType.CSV

    def fetch(self, spec: SourceSpec) -> list[RawRecord]:
        """Read all non-empty rows of the file at ``spec.path``.

        Args:
            spec: A CSV source spec.

        Returns:
            One raw record per non-empty row; the id falls back to ``row-<n>``
            (1-based data row number) when no id column exists.

        Raises:
            IngestionError: If the file is missing, unparsable, or has no
                SMILES/InChI column.
        """
        if spec.source is not SourceType.CSV or spec.path is None:
            raise IngestionError("CsvConnector requires a csv spec with a path")
        frame = _read_frame(Path(spec.path))
        mapped = {canonical_field(str(c)) for c in frame.columns}
        if not mapped.intersection(IDENTIFIER_FIELDS):
            raise IngestionError(
                f"{spec.path}: no identifier column (need one of {', '.join(IDENTIFIER_FIELDS)})"
            )
        records = [
            build_raw_record(SourceType.CSV, _row_values(row), fallback_id=f"row-{index + 1}")
            for index, row in enumerate(frame.to_dict(orient="records"))
        ]
        logger.info("csv read", extra={"path": spec.path, "records": len(records)})
        return records


def _read_frame(path: Path) -> pd.DataFrame:
    """Load the file into an all-string DataFrame, dropping fully blank rows."""
    if not path.is_file():
        raise IngestionError(f"CSV file not found: {path}")
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            sample = handle.read(4096)
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter if sample else ","
    except (csv.Error, UnicodeDecodeError):
        delimiter = ","
    try:
        with warnings.catch_warnings():
            # Ragged rows surface as ParserWarning with index_col=False; treat as errors.
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(
                path,
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
                index_col=False,
            )
    except (
        pd.errors.ParserError,
        pd.errors.ParserWarning,
        pd.errors.EmptyDataError,
        UnicodeDecodeError,
    ) as exc:
        raise IngestionError(f"cannot parse CSV {path}: {exc}") from exc
    frame.columns = [str(c).strip() for c in frame.columns]
    blank = frame.apply(lambda r: all(not str(v).strip() for v in r), axis=1)
    return frame.loc[~blank] if len(frame) else frame


def _row_values(row: dict[object, object]) -> dict[str, JsonScalar]:
    """Convert a DataFrame row to string-keyed scalars."""
    return {str(k): (None if v is None else str(v)) for k, v in row.items()}
