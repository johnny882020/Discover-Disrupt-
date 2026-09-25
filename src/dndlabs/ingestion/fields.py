"""Shared helpers for building ``RawRecord`` instances from flat source rows."""

from collections.abc import Mapping
from typing import Any

from dndlabs.core.schemas import RawRecord, SourceType

#: Canonical ``RawRecord`` field -> accepted source aliases (lower-case).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_record_id": (
        "source_record_id", "compound_id", "id", "sample_id", "cid", "molecule_chembl_id",
    ),
    "name": ("name", "compound_name", "title"),
    "smiles": ("smiles", "canonical_smiles", "isomeric_smiles"),
    "inchi": ("inchi",),
    "inchikey": ("inchikey", "inchi_key"),
    "molecular_formula": ("molecular_formula", "formula"),
    "molecular_weight": ("molecular_weight", "mw", "mol_weight"),
    "target": ("target", "target_name", "target_chembl_id"),
    "assay_type": ("assay_type", "standard_type", "activity_type", "measurement"),
    "activity_value": ("activity_value", "value", "standard_value", "concentration"),
    "activity_unit": ("activity_unit", "unit", "units", "standard_units"),
    "activity_relation": ("activity_relation", "relation", "standard_relation"),
}  # fmt: skip

_ALIAS_TO_FIELD = {alias: field for field, aliases in FIELD_ALIASES.items() for alias in aliases}

IDENTIFIER_FIELDS = ("smiles", "inchi")
NUMERIC_FIELDS = ("molecular_weight", "activity_value")


def canonical_field(column: str) -> str | None:
    """Map a source column name to a ``RawRecord`` field.

    Args:
        column: Source column or key name.

    Returns:
        The canonical field name, or ``None`` if the column is not recognised.
    """
    return _ALIAS_TO_FIELD.get(column.strip().lower())


def _clean(value: Any) -> Any:
    """Normalize blank strings to ``None`` and strip whitespace."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def _coerce(field: str, value: Any) -> Any:
    """Coerce a cleaned value to the type ``RawRecord`` expects for ``field``."""
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
        cleaned = _clean(value)
        field = canonical_field(column)
        if field is None:
            extra[column] = cleaned
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
