import pytest

from dndlabs.core.schemas import Severity
from dndlabs.validation.units import UnitNormalizationRule, nanomolar_factor
from tests.unit.validation.helpers import raw, seed

RULE = UnitNormalizationRule()


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1.5", "uM", 1500.0),
        ("2", "µM", 2000.0),
        ("2", "μM", 2000.0),
        ("0.002", "mM", 2_000_000.0 / 1000),
        ("3", "nM", 3.0),
        ("500", "pM", 0.5),
        ("1e-6", "M", 1000.0),
        ("7", "nmol/L", 7.0),
        ("7", " NM ", 7.0),
        (4.0, "umol/l", 4000.0),
        ("0", "nM", 0.0),
    ],
)
def test_conversions(value: str | float, unit: str, expected: float) -> None:
    r = raw(activity_value=value, activity_unit=unit)
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    assert outcome.record.activity_value_nm == pytest.approx(expected)


def test_lowercase_m_is_ambiguous() -> None:
    assert nanomolar_factor("m") is None
    assert nanomolar_factor("M") == 1e9


@pytest.mark.parametrize(
    ("value", "unit", "field", "fragment"),
    [
        ("abc", "nM", "activity_value", "not numeric"),
        ("-5", "nM", "activity_value", "negative"),
        ("7", None, "activity_unit", "no unit"),
        ("5", "furlongs", "activity_unit", "unsupported"),
        ("5", "mg/mL", "activity_unit", "unsupported"),
    ],
)
def test_errors(value: str, unit: str | None, field: str, fragment: str) -> None:
    r = raw(activity_value=value, activity_unit=unit)
    outcome = RULE.apply(r, seed(r))
    [issue] = outcome.issues
    assert issue.severity is Severity.ERROR
    assert issue.field == field
    assert fragment in issue.message
    assert outcome.record.activity_value_nm is None


def test_no_activity_is_fine() -> None:
    r = raw()
    assert RULE.apply(r, seed(r)).issues == []


def test_unit_without_value_warns() -> None:
    r = raw(activity_unit="nM")
    [issue] = RULE.apply(r, seed(r)).issues
    assert issue.severity is Severity.WARNING
