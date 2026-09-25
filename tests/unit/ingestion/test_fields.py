from dndlabs.core.schemas import SourceType
from dndlabs.ingestion.fields import build_raw_record, canonical_field


def test_canonical_field_aliases() -> None:
    assert canonical_field(" SMILES ") == "smiles"
    assert canonical_field("standard_units") == "activity_unit"
    assert canonical_field("unknown") is None


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
