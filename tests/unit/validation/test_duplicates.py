import uuid

from dndlabs.core.schemas import NormalizedRecord, Severity, SourceType
from dndlabs.validation.duplicates import DuplicateRule

DATASET_ID = uuid.uuid4()


def _rec(sid: str, key: str | None) -> NormalizedRecord:
    return NormalizedRecord(
        dataset_id=DATASET_ID, source=SourceType.CSV, source_record_id=sid, record_key=key
    )


def test_first_occurrence_wins() -> None:
    records = [_rec("a", "K1"), _rec("b", "K2"), _rec("c", "K1"), _rec("d", "K1")]
    outcome = DuplicateRule().apply(records)
    assert [r.source_record_id for r in outcome.kept] == ["a", "b"]
    assert [r.source_record_id for r in outcome.dropped] == ["c", "d"]
    assert all(i.severity is Severity.WARNING for i in outcome.issues)


def test_records_without_key_are_kept() -> None:
    outcome = DuplicateRule().apply([_rec("a", None), _rec("b", None)])
    assert len(outcome.kept) == 2
    assert outcome.issues == []


def test_empty() -> None:
    assert DuplicateRule().apply([]).kept == []


def test_the_same_compound_in_another_context_is_kept() -> None:
    from dndlabs.core.schemas import AssayFormat, ControlType

    bio = _rec("bio", "K1").model_copy(update={"assay_format": AssayFormat.BIOCHEMICAL})
    cell = _rec("cell", "K1").model_copy(update={"assay_format": AssayFormat.CELL_BASED})
    other_target = _rec("egfr", "K1").model_copy(
        update={"assay_format": AssayFormat.BIOCHEMICAL, "target": "EGFR"}
    )
    control = _rec("ctrl", "K1").model_copy(
        update={"assay_format": AssayFormat.BIOCHEMICAL, "control": ControlType.POSITIVE}
    )
    repeat = _rec("again", "K1").model_copy(update={"assay_format": AssayFormat.BIOCHEMICAL})
    outcome = DuplicateRule().apply([bio, cell, other_target, control, repeat])
    assert [r.source_record_id for r in outcome.kept] == ["bio", "cell", "egfr", "ctrl"]
    assert [r.source_record_id for r in outcome.dropped] == ["again"]
    assert "same target and assay" in outcome.issues[0].message


def test_context_key_ignores_case_and_is_empty_without_context() -> None:
    plain = _rec("a", "K1")
    assert plain.context_key() == ""
    upper = plain.model_copy(update={"target": " EGFR ", "assay_type": "IC50"})
    lower = plain.model_copy(update={"target": "egfr", "assay_type": "ic50"})
    assert upper.context_key() == lower.context_key() != ""
