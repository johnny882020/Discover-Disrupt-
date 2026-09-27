import pytest
from tests.unit.validation.helpers import ASPIRIN, raw, seed

from dndlabs.core.schemas import AssayFormat, ControlType, Severity
from dndlabs.validation.assay_context import AssayContextRule


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Biochemical", AssayFormat.BIOCHEMICAL),
        ("enzymatic", AssayFormat.BIOCHEMICAL),
        ("cell-free", AssayFormat.BIOCHEMICAL),
        ("Cell-based", AssayFormat.CELL_BASED),
        ("cell_based", AssayFormat.CELL_BASED),
        ("Cellular", AssayFormat.CELL_BASED),
    ],
)
def test_assay_format_spellings(value: str, expected: AssayFormat) -> None:
    r = raw(smiles=ASPIRIN, assay_format=value)
    outcome = AssayContextRule().apply(r, seed(r))
    assert outcome.record.assay_format is expected
    assert outcome.issues == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Positive control", ControlType.POSITIVE),
        ("+", ControlType.POSITIVE),
        ("neg", ControlType.NEGATIVE),
        ("-", ControlType.NEGATIVE),
        ("no", None),
        ("test", None),
    ],
)
def test_control_spellings(value: str, expected: ControlType | None) -> None:
    r = raw(smiles=ASPIRIN, control=value)
    outcome = AssayContextRule().apply(r, seed(r))
    assert outcome.record.control is expected
    assert outcome.issues == []


def test_unrecognized_values_warn_and_keep_the_record() -> None:
    r = raw(smiles=ASPIRIN, assay_format="in vivo", control="maybe")
    outcome = AssayContextRule().apply(r, seed(r))
    assert (outcome.record.assay_format, outcome.record.control) == (None, None)
    assert [i.field for i in outcome.issues] == ["assay_format", "control"]
    assert all(i.severity is Severity.WARNING for i in outcome.issues)


def test_no_context_is_left_empty() -> None:
    r = raw(smiles=ASPIRIN)
    outcome = AssayContextRule().apply(r, seed(r))
    assert (outcome.record.assay_format, outcome.record.control, outcome.issues) == (None, None, [])
