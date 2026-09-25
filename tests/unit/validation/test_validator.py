import uuid

from tests.unit.validation.helpers import ASPIRIN, CAFFEINE, CAFFEINE_AROMATIC, raw

from dndlabs.core.schemas import Severity
from dndlabs.validation.validator import Validator, build_report

RUN_ID = uuid.uuid4()
DATASET_ID = uuid.uuid4()


def test_clean_dataset() -> None:
    raws = [
        raw("1", name="Aspirin", smiles=ASPIRIN, activity_value="1", activity_unit="uM"),
        raw("2", name="Caffeine", smiles=CAFFEINE),
    ]
    outcome = Validator().run(RUN_ID, DATASET_ID, raws)
    report = outcome.report
    assert [r.source_record_id for r in outcome.accepted] == ["1", "2"]
    assert outcome.accepted[0].activity_value_nm == 1000.0
    assert report.run_id == RUN_ID
    assert report.dataset_id == DATASET_ID
    assert (report.total_records, report.accepted_records) == (2, 2)
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
    ]
    outcome = Validator().run(RUN_ID, DATASET_ID, raws)
    report = outcome.report
    assert [r.source_record_id for r in outcome.accepted] == ["ok", "caf"]
    assert report.total_records == 7
    assert report.accepted_records == 2
    assert report.rejected_records == 3
    assert report.duplicate_records == 2
    rejected_ids = {i.source_record_id for i in report.issues if i.severity is Severity.ERROR}
    assert rejected_ids == {"bad-smiles", "bad-unit", "no-id"}


def test_empty_input() -> None:
    outcome = Validator().run(RUN_ID, DATASET_ID, [])
    assert outcome.accepted == []
    assert outcome.report.pass_rate == 0.0


def test_build_report_rounds_pass_rate() -> None:
    report = build_report(RUN_ID, DATASET_ID, 3, 1, 2, 0, [])
    assert report.pass_rate == 0.3333
