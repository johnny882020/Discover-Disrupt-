"""Read uploaded or on-disk tables (CSV, TSV, XLSX, SDF, SMILES, MOL) into a uniform shape.

Every reader returns a :class:`Table`: header names plus rows of strings
(``""`` for a missing value), with fully blank rows dropped. Nothing is
interpreted here — which column holds what is decided by a column mapping.
Cell values are kept exactly as written (headers are trimmed): whitespace
can be significant, as in a MOL block's blank title line, and values are
cleaned per field when records are built (``ingestion/fields.py``).
"""

import csv
import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath

import pandas as pd
from openpyxl import load_workbook  # type: ignore[import-untyped]
from rdkit import Chem, RDLogger

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.schemas import UploadFormat

RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]

#: File extension -> format. ``.txt`` is treated as delimited text.
_EXTENSIONS: dict[str, UploadFormat] = {
    ".csv": UploadFormat.CSV,
    ".txt": UploadFormat.CSV,
    ".tsv": UploadFormat.TSV,
    ".tab": UploadFormat.TSV,
    ".xlsx": UploadFormat.XLSX,
    ".sdf": UploadFormat.SDF,
    ".sd": UploadFormat.SDF,
    ".smi": UploadFormat.SMI,
    ".smiles": UploadFormat.SMI,
    ".mol": UploadFormat.MOL,
}


@dataclass(frozen=True)
class Table:
    """A parsed table: ordered column names and string-valued rows."""

    columns: list[str]
    rows: list[dict[str, str]]


def upload_format(filename: str) -> UploadFormat:
    """Determine an upload's format from its file name.

    Args:
        filename: The client-supplied file name.

    Returns:
        The format.

    Raises:
        IngestionError: If the extension is not a supported format.
    """
    suffix = PurePath(filename).suffix.lower()
    if suffix not in _EXTENSIONS:
        supported = ", ".join(sorted(_EXTENSIONS))
        raise IngestionError(f"unsupported file type {suffix or '(none)'}; use one of {supported}")
    return _EXTENSIONS[suffix]


def read_table(data: bytes, fmt: UploadFormat, max_rows: int) -> Table:
    """Parse file bytes of the given format.

    Args:
        data: The file content.
        fmt: Its format.
        max_rows: Refuse files with more data rows than this.

    Returns:
        The table.

    Raises:
        IngestionError: If the content cannot be parsed, has no columns, or
            exceeds ``max_rows``.
    """
    if fmt is UploadFormat.XLSX:
        table = _read_xlsx(data)
    elif fmt is UploadFormat.SDF:
        table = _read_sdf(data)
    elif fmt is UploadFormat.SMI:
        table = _read_smi(decode_text(data))
    elif fmt is UploadFormat.MOL:
        table = _read_mol(decode_text(data))
    else:
        text = decode_text(data)
        table = read_delimited(text, "\t" if fmt is UploadFormat.TSV else None)
    if not table.columns:
        raise IngestionError("the file has no columns")
    if len(table.rows) > max_rows:
        raise IngestionError(f"the file has {len(table.rows)} rows; the limit is {max_rows}")
    return table


def read_delimited(text: str, delimiter: str | None = None) -> Table:
    """Parse delimited text, sniffing ``,`` ``;`` or tab when no delimiter is given.

    Args:
        text: The file content.
        delimiter: The delimiter, or ``None`` to detect it.

    Returns:
        The table.

    Raises:
        IngestionError: If the text is empty or rows have too many fields.
    """
    if delimiter is None:
        # Sniffing the first 4 KiB is enough to see a few rows; comma is the
        # fallback when the sample is ambiguous (e.g. a single column).
        sample = text[:4096]
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter if sample else ","
        except csv.Error:
            delimiter = ","
    try:
        # dtype=str and keep_default_na=False keep every cell as written
        # ("NA", "null" and "" would otherwise become NaN). With
        # index_col=False pandas only warns about a row with too many fields
        # and drops the surplus, so that warning is escalated to an error
        # rather than losing data silently.
        with warnings.catch_warnings():
            warnings.simplefilter("error", pd.errors.ParserWarning)
            frame = pd.read_csv(
                io.StringIO(text),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
                index_col=False,
            )
    except (pd.errors.ParserError, pd.errors.ParserWarning, pd.errors.EmptyDataError) as exc:
        raise IngestionError(f"cannot parse delimited text: {exc}") from exc
    columns = [str(c).strip() for c in frame.columns]
    rows = [
        {column: str(value) for column, value in zip(columns, values, strict=True)}
        for values in frame.itertuples(index=False, name=None)
    ]
    return Table(columns=columns, rows=_without_blank_rows(rows))


def decode_text(data: bytes) -> str:
    """Decode text as UTF-8 (with or without BOM), falling back to Windows-1252.

    Windows-1252 covers legacy Excel/instrument exports; ``errors="replace"``
    because a few of its byte values are undefined, so decoding never fails.
    Shared by uploads and the CSV connector, so a file reads the same both ways.

    Args:
        data: The file's bytes.

    Returns:
        The decoded text.
    """
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _read_xlsx(data: bytes) -> Table:
    """Read the first worksheet; the first non-empty row is the header."""
    try:
        # read_only streams rows instead of loading the whole workbook;
        # data_only returns formulas' cached values rather than their text.
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many unrelated types for corrupt files
        raise IngestionError(f"cannot read the Excel workbook: {exc}") from exc
    try:
        sheet = workbook.worksheets[0]
        values = [
            ["" if cell is None else _cell_text(cell) for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
    finally:
        workbook.close()
    values = [row for row in values if any(cell.strip() for cell in row)]
    if not values:
        return Table(columns=[], rows=[])
    columns = _unique_headers(values[0])
    rows = [
        {column: (row[i] if i < len(row) else "") for i, column in enumerate(columns)}
        for row in values[1:]
    ]
    return Table(columns=columns, rows=rows)


def _cell_text(value: object) -> str:
    """Render a spreadsheet cell as text (whole-number floats without ``.0``).

    Spreadsheet numbers are doubles, so a whole-number ID can be read back
    as a float and would otherwise come out as ``"2244.0"``.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _read_sdf(data: bytes) -> Table:
    """Read an SD file: one row per molecule, SMILES plus its data fields.

    Molecules are read unsanitized, so a structure RDKit rejects still yields
    a row (with its SMILES as written) for validation to report, rather than
    being dropped silently.
    """
    supplier = Chem.ForwardSDMolSupplier(io.BytesIO(data), sanitize=False, removeHs=False)
    columns = ["smiles", "name"]
    rows: list[dict[str, str]] = []
    for mol in supplier:
        # Even unsanitized, RDKit returns None for an unparsable record; it
        # still gets an (empty) row so the row count matches the file and
        # validation can report it.
        if mol is None:
            rows.append({"smiles": "", "name": ""})
            continue
        row = {
            "smiles": mol_to_smiles(mol),
            "name": str(mol.GetProp("_Name")).strip() if mol.HasProp("_Name") else "",
        }
        for prop in mol.GetPropNames():
            if prop not in columns:
                columns.append(prop)
            row[prop] = str(mol.GetProp(prop)).strip()
        rows.append(row)
    if not rows:
        raise IngestionError("the SD file contains no molecules")
    filled = [{column: row.get(column, "") for column in columns} for row in rows]
    return Table(columns=columns, rows=filled)


def _read_smi(text: str) -> Table:
    """Read a SMILES file: one ``SMILES [name]`` per line, whitespace-separated.

    Blank lines and ``#`` comments are skipped, as is a first line whose
    first field is the word ``smiles`` (a header).
    """
    rows: list[dict[str, str]] = []
    for number, line in enumerate(text.splitlines()):
        fields = line.split(maxsplit=1)
        if not fields or fields[0].startswith("#"):
            continue
        if number == 0 and fields[0].lower() == "smiles":
            continue
        rows.append({"smiles": fields[0], "name": fields[1].strip() if len(fields) > 1 else ""})
    if not rows:
        raise IngestionError("the SMILES file contains no structures")
    return Table(columns=["smiles", "name"], rows=rows)


def _read_mol(text: str) -> Table:
    """Read a MOL file: a single molecule, as one row of SMILES and name."""
    mol = Chem.MolFromMolBlock(text, sanitize=False, removeHs=False)
    if mol is None:
        raise IngestionError("cannot read the MOL file")
    # A MOL block's first line is its title, the molecule's name.
    name = text.splitlines()[0].strip() if text.strip() else ""
    return Table(columns=["smiles", "name"], rows=[{"smiles": mol_to_smiles(mol), "name": name}])


def mol_to_smiles(mol: Chem.Mol) -> str:
    """Canonical SMILES of a sanitized copy, or the SMILES as written if RDKit rejects it."""
    sanitized = Chem.Mol(mol)
    failed = Chem.SanitizeMol(sanitized, catchErrors=True)
    return str(Chem.MolToSmiles(mol if failed else sanitized))


def _unique_headers(cells: list[str]) -> list[str]:
    """Name blank headers ``column_<n>`` and suffix repeated ones (``x``, ``x_2``)."""
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, cell in enumerate(cells):
        name = cell.strip() or f"column_{index + 1}"
        seen[name] = seen.get(name, 0) + 1
        headers.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return headers


def _without_blank_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop rows whose every value is empty or whitespace."""
    return [row for row in rows if any(value.strip() for value in row.values())]
