from collections.abc import Sequence

from dndlabs.core.schemas import (
    DatasetRuleOutcome,
    NormalizedRecord,
    RawRecord,
    RuleOutcome,
    Severity,
)
from dndlabs.validation.issues import error
from dndlabs.validation.validator import Validator, build_report
from tests.unit.validation.helpers import (
    ASPIRIN,
    ASPIRIN_KEY,
    CAFFEINE,
    CAFFEINE_AROMATIC,
    raw,
)


def test_clean_dataset() -> None:
    raws = [
        raw("1", name="Aspirin", smiles=ASPIRIN, activity_value="1", activity_unit="uM"),
        raw("2", name="Caffeine", smiles=CAFFEINE),
    ]
    outcome = Validator().run("run-1", raws)
    report = outcome.report
    assert [r.source_record_id for r in outcome.accepted] == ["1", "2"]
    assert outcome.accepted[0].record_key == ASPIRIN_KEY
    assert outcome.accepted[0].activity_value_nm == 1000.0
    assert outcome.accepted[0].name == "Aspirin"
    assert report.run_id == "run-1"
    assert (report.total_records, report.accepted_records) == (2, 2)
    assert (report.rejected_records, report.duplicate_records) == (0, 0)
    assert report.issues == []
    assert report.pass_rate == 1.0


def test_dirty_dataset_report() -> None:
    raws = [
        raw("ok", smiles=ASPIRIN),
        raw("dup", smiles=ASPIRIN),
        raw("caf", smiles=CAFFEINE),
        raw("caf2", smiles=CAFFEINE_AROMATIC, inchikey="WRONG-KEY"),
        raw("bad-smiles", smiles="C1CC("),
        raw("bad-unit", smiles="CCO", activity_value="5", activity_unit="furlongs"),
        raw("no-id", name="x"),
        raw("many", smiles="C1CC(", activity_value="x", activity_unit="nM"),
    ]
    outcome = Validator().run("r", raws)
    report = outcome.report
    assert [r.source_record_id for r in outcome.accepted] == ["ok", "caf"]
    assert report.total_records == 8
    assert report.accepted_records == 2
    assert report.rejected_records == 4
    assert report.duplicate_records == 2
    assert report.error_count == 5
    assert report.warning_count == 3  # caf2 key mismatch + 2 duplicates
    assert report.issues_by_rule == {
        "compound_identity": 3,
        "duplicates": 2,
        "schema": 1,
        "unit_normalization": 2,
    }
    assert report.pass_rate == 0.25
    rejected_ids = {i.source_record_id for i in report.issues if i.severity is Severity.ERROR}
    assert rejected_ids == {"bad-smiles", "bad-unit", "no-id", "many"}


def test_empty_input() -> None:
    outcome = Validator().run("r", [])
    assert outcome.accepted == []
    assert outcome.report.pass_rate == 0.0


class _AlwaysFails:
    name = "always_fails"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        return RuleOutcome(record=record, issues=[error(self.name, record, "nope")])


class _KeepAll:
    name = "keep_all"

    def apply(self, records: Sequence[NormalizedRecord]) -> DatasetRuleOutcome:
        return DatasetRuleOutcome(kept=list(records))


def test_custom_rules_are_pluggable() -> None:
    outcome = Validator([_AlwaysFails()], [_KeepAll()]).run("r", [raw("1", smiles="C")])
    assert outcome.accepted == []
    assert outcome.report.issues_by_rule == {"always_fails": 1}


def test_build_report_rounds_pass_rate() -> None:
    report = build_report("r", 3, 1, 2, 0, [])
    assert report.pass_rate == 0.3333
