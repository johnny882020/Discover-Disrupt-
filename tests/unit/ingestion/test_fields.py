from dndlabs.core.schemas import SourceType
from dndlabs.ingestion.fields import build_raw_record, canonical_field


def test_canonical_field_aliases() -> None:
    assert canonical_field(" SMILES ") == "smiles"
    assert canonical_field("standard_units") == "activity_unit"
    assert canonical_field("unknown") is None


def test_canonical_field_ignores_case_spacing_and_punctuation() -> None:
    assert canonical_field("Compound ID") == "source_record_id"
    assert canonical_field("Canonical SMILES") == "smiles"
    assert canonical_field("Molecular-Weight") == "molecular_weight"
    assert canonical_field("  Activity  Value ") == "activity_value"
    assert canonical_field("IC50 (nM)") is None  # a unit in the header is not a unit column


def test_build_raw_record_coerces_and_collects_extra() -> None:
    record = build_raw_record(
        SourceType.JSON,
        {"id": 5, "mw": 12, "name": "  ", "smiles": " CCO ", "flag": True, "unit": None},
        fallback_id="x",
    )
    assert record.source_record_id == "5"
    assert record.molecular_weight == 12.0
    assert record.name is None
    assert record.smiles == "CCO"
    assert record.extra == {"flag": True}


def test_first_non_empty_alias_wins() -> None:
    record = build_raw_record(
        SourceType.CSV, {"smiles": "", "canonical_smiles": "CC", "value": True}, "row-1"
    )
    assert record.smiles == "CC"
    assert record.activity_value == "True"


def test_build_mapped_record_applies_roles_ignores_and_keeps_extras() -> None:
    from dndlabs.core.schemas import ColumnRole, SourceType
    from dndlabs.ingestion.fields import build_mapped_record

    record = build_mapped_record(
        SourceType.UPLOAD,
        {"Struct": " CCO ", "Potency": "12", "Unit": "nM", "Batch": "B7", "Junk": "x", "ID": ""},
        {
            "Struct": ColumnRole.SMILES,
            "Potency": ColumnRole.ACTIVITY_VALUE,
            "Unit": ColumnRole.ACTIVITY_UNIT,
            "Junk": ColumnRole.IGNORE,
            "ID": ColumnRole.SOURCE_RECORD_ID,
        },
        fallback_id="row-3",
    )
    assert record.smiles == "CCO"
    assert (record.activity_value, record.activity_unit) == ("12", "nM")
    assert record.extra == {"Batch": "B7"}
    assert record.source_record_id == "row-3"  # the id column was empty
