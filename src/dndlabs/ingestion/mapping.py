"""Suggest which column of an uploaded table holds what.

Suggestions come from three sources, in order of precedence:

1. a saved mapping template whose headers the table contains (the one that
   covers the most columns wins);
2. known header aliases (``smiles``, ``mw``, ``standard_value``, …);
3. the content itself, for structure columns under unfamiliar headers:
   ``InChI=`` strings, InChIKeys, and values RDKit parses as SMILES.

Content is never used to suggest a PubChem CID or a name to look up: a lookup
sends the column's values to PubChem, so those roles come only from a template
or an explicit header, and the user confirms or corrects the suggestion before
a run uses it.
"""

import re
from collections.abc import Callable, Sequence

from rdkit import Chem, RDLogger

from dndlabs.core.schemas import LOOKUP_ROLES, STRUCTURE_ROLES, ColumnRole, MappingTemplate
from dndlabs.ingestion.fields import canonical_field
from dndlabs.ingestion.tabular import Table

RDLogger.DisableLog("rdApp.*")  # type: ignore[attr-defined]

#: How many non-empty values of a column are sampled for content detection.
_SAMPLE = 20
#: Share of sampled values that must match for an InChI/InChIKey column.
_THRESHOLD = 0.8
#: Share of sampled values that must parse for a SMILES column. Lower, because
#: the files people need cleaned are the ones with some invalid structures.
_SMILES_PARSE_THRESHOLD = 0.5
_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_CHEMBL_ID = re.compile(r"^CHEMBL\d+$")
#: Structures read from the file itself, as opposed to identifiers looked up.
_DIRECT_STRUCTURE_ROLES = STRUCTURE_ROLES - LOOKUP_ROLES
_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_SMILES_CHARS = re.compile(r"^[A-Za-z0-9@+\-\[\]()=#$%/\\.:*~]+$")


def suggest_mapping(
    table: Table, templates: Sequence[MappingTemplate]
) -> tuple[dict[str, ColumnRole], MappingTemplate | None]:
    """Suggest a role for the table's columns.

    Args:
        table: The parsed table.
        templates: The organization's saved templates.

    Returns:
        ``(mapping, template)``: column -> suggested role (unrecognized
        columns are omitted, i.e. kept as extra data), and the template the
        suggestion came from, if any.
    """
    template = _best_template(table.columns, templates)
    if template is not None:
        return {c: r for c, r in template.mapping.items() if c in table.columns}, template

    mapping: dict[str, ColumnRole] = {}
    for column in table.columns:
        field = canonical_field(column)
        # One column per role: the first header claiming it wins, since a
        # mapping with two SMILES columns would be ambiguous.
        if field is not None and ColumnRole(field) not in mapping.values():
            mapping[column] = ColumnRole(field)
    # Sniff contents unless the file's structures are already readable
    # directly; an identifier column alone (e.g. InChIKey) still gets a
    # search for a SMILES/InChI/MOL column beside it.
    if not _DIRECT_STRUCTURE_ROLES.intersection(mapping.values()):
        for column in table.columns:
            if column in mapping:
                continue
            role = _structure_role(_sample(table, column))
            if role is not None and role not in mapping.values():
                mapping[column] = role
    return mapping, None


def _best_template(
    columns: Sequence[str], templates: Sequence[MappingTemplate]
) -> MappingTemplate | None:
    """The template whose headers all appear in ``columns`` and cover the most of them."""
    present = set(columns)
    matching = [t for t in templates if t.mapping and set(t.mapping) <= present]
    return max(matching, key=lambda t: len(t.mapping), default=None)


def _sample(table: Table, column: str) -> list[str]:
    """Up to ``_SAMPLE`` non-empty values of a column, trimmed."""
    values = (row.get(column, "").strip() for row in table.rows)
    return [v for v in values if v][:_SAMPLE]


def _structure_role(values: Sequence[str]) -> ColumnRole | None:
    """Recognize a column of InChI, MOL block, InChIKey, ChEMBL ID or SMILES values.

    Names and PubChem CIDs are never suggested: they cannot be told apart
    from internal codes or numbers, and a lookup role sends values to
    PubChem, so the user must choose it.
    """
    if not values:
        return None

    def share(predicate: Callable[[str], bool]) -> float:
        return sum(1 for v in values if predicate(v)) / len(values)

    if share(lambda v: v.startswith("InChI=")) >= _THRESHOLD:
        return ColumnRole.INCHI
    if share(lambda v: "M  END" in v) >= _THRESHOLD:
        return ColumnRole.MOL_BLOCK
    if share(lambda v: _INCHIKEY.match(v) is not None) >= _THRESHOLD:
        return ColumnRole.INCHIKEY
    if share(lambda v: _CHEMBL_ID.match(v.upper()) is not None) >= _THRESHOLD:
        return ColumnRole.CHEMBL_ID
    # Every value must look like SMILES (cheap regex, rules out prose and plain
    # numbers such as IDs) before RDKit is asked to parse them.
    if all(_smiles_shaped(v) for v in values) and (
        share(lambda v: Chem.MolFromSmiles(v) is not None) >= _SMILES_PARSE_THRESHOLD
    ):
        return ColumnRole.SMILES
    return None


def _smiles_shaped(value: str) -> bool:
    """True for text made only of SMILES characters that is not a plain number."""
    return _SMILES_CHARS.match(value) is not None and _NUMBER.match(value) is None
