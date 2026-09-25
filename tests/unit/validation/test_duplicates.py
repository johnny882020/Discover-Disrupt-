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
