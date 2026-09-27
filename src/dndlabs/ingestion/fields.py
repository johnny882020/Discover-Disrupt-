"""Shared helpers for building ``RawRecord`` instances from flat source rows.

Two paths: :func:`build_raw_record` matches columns by header alias (CSV and
JSON connectors); :func:`build_mapped_record` applies a user-confirmed column
mapping (uploads). The same aliases seed the upload mapping suggestion
(``ingestion/mapping.py``).
"""

import re
from collections.abc import Mapping
from typing import Any

from dndlabs.core.schemas import ColumnRole, RawRecord, SourceType

#: Canonical ``RawRecord`` field -> accepted source aliases, in normalized form
#: (see :func:`normalize_header`).
#:
#: Plain ``name``/``title`` headers map to ``name`` (a label) and ``cid`` to the
#: record id, so a column is never looked up in PubChem just for being called
#: "Name" or "CID"; the lookup fields (``pubchem_cid``, ``lookup_name``, …) need
#: their explicit header. Assay-format and control *values* are normalized
#: later, in ``validation/assay_context.py``.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_record_id": (
        "source_record_id", "compound_id", "id", "sample_id", "cid", "molecule_chembl_id",
    ),
    "name": ("name", "compound_name", "title"),
    "smiles": ("smiles", "canonical_smiles", "isomeric_smiles"),
    "inchi": ("inchi",),
    "mol_block": ("mol_block", "molblock", "molfile", "ctab"),
    "inchikey": ("inchikey", "inchi_key"),
    "pubchem_cid": ("pubchem_cid",),
    "chembl_id": ("chembl_id",),
    "lookup_name": ("lookup_name",),
    "molecular_formula": ("molecular_formula", "formula"),
    "molecular_weight": ("molecular_weight", "mw", "mol_weight"),
    "target": ("target", "target_name", "target_chembl_id"),
    "assay_type": ("assay_type", "standard_type", "activity_type", "measurement"),
    "assay_format": ("assay_format",),
    "control": ("control", "control_type", "is_control"),
    "activity_value": ("activity_value", "value", "standard_value", "concentration"),
    "activity_unit": ("activity_unit", "unit", "units", "standard_units"),
    "activity_relation": ("activity_relation", "relation", "standard_relation"),
}  # fmt: skip

_ALIAS_TO_FIELD = {alias: field for field, aliases in FIELD_ALIASES.items() for alias in aliases}

#: Fields that identify a record's structure, read directly or looked up.
IDENTIFIER_FIELDS = (
    "smiles", "inchi", "mol_block", "inchikey", "pubchem_cid", "chembl_id", "lookup_name",
)  # fmt: skip
NUMERIC_FIELDS = ("molecular_weight", "activity_value")


_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_header(column: str) -> str:
    """Normalize a column name for alias lookup.

    Lower-cases it and turns every run of other characters into a single
    underscore, so ``"Compound ID"``, ``"compound-id"`` and ``"COMPOUND_ID"``
    all become ``"compound_id"``.

    Args:
        column: Source column or key name.

    Returns:
        The normalized name.
    """
    return _SEPARATORS.sub("_", column.lower()).strip("_")


def canonical_field(column: str) -> str | None:
    """Map a source column name to a ``RawRecord`` field.

    Args:
        column: Source column or key name.

    Returns:
        The canonical field name, or ``None`` if the column is not recognised.
    """
    return _ALIAS_TO_FIELD.get(normalize_header(column))


def _clean(value: Any, field: str | None = None) -> Any:
    """Normalize blank strings to ``None`` and strip whitespace.

    A MOL block keeps its layout: its first line (the title) may be blank,
    and removing it would make the block unreadable.
    """
    if isinstance(value, str):
        if not value.strip():
            return None
        return value if field == "mol_block" else value.strip()
    return value


def _coerce(field: str, value: Any) -> Any:
    """Coerce a cleaned value to the type ``RawRecord`` expects for ``field``."""
    # bool is checked before the numeric branch: it is an int subclass, and
    # float(True) would silently turn a JSON flag into 1.0.
    if value is None or isinstance(value, bool):
        return None if value is None else str(value)
    if field in NUMERIC_FIELDS:
        return value if isinstance(value, str) else float(value)
    return str(value)


def build_raw_record(source: SourceType, row: Mapping[str, Any], fallback_id: str) -> RawRecord:
    """Build a ``RawRecord`` from a flat source row.

    Recognised columns map onto typed fields; everything else lands in
    ``extra``. Numeric-looking fields are kept as given so validation can
    report bad values.

    Args:
        source: Source the row came from.
        row: Column name -> value.
        fallback_id: Record id to use when the row has none.

    Returns:
        The raw record.
    """
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for column, value in row.items():
        field = canonical_field(column)
        cleaned = _clean(value, field)
        if field is None:
            extra[column] = cleaned
        # First non-empty column wins when several alias the same field.
        elif fields.get(field) is None:
            fields[field] = _coerce(field, cleaned)
    record_id = fields.pop("source_record_id", None)
    return RawRecord.model_validate(
        {
            **fields,
            "source": source,
            "source_record_id": str(record_id) if record_id is not None else fallback_id,
            "extra": extra,
        }
    )


def build_mapped_record(
    source: SourceType, row: Mapping[str, Any], mapping: Mapping[str, ColumnRole], fallback_id: str
) -> RawRecord:
    """Build a ``RawRecord`` from a row using an explicit column mapping.

    Mapped columns fill their ``RawRecord`` field; ``ignore`` columns are
    dropped; unmapped columns land in ``extra``.

    Args:
        source: Source the row came from.
        row: Column name -> value.
        mapping: Column name -> role.
        fallback_id: Record id to use when no column is mapped to one.

    Returns:
        The raw record.
    """
    fields: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for column, value in row.items():
        role = mapping.get(column)
        cleaned = _clean(value, role.value if role is not None else None)
        if role is None:
            extra[column] = cleaned
        elif role is not ColumnRole.IGNORE:
            fields[role.value] = _coerce(role.value, cleaned)
    record_id = fields.pop("source_record_id", None)
    return RawRecord.model_validate(
        {
            **fields,
            "source": source,
            "source_record_id": str(record_id) if record_id is not None else fallback_id,
            "extra": extra,
        }
    )
