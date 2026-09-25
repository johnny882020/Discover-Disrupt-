import pytest
from tests.unit.validation.helpers import raw, seed

from dndlabs.core.schemas import Severity
from dndlabs.validation.units import UnitNormalizationRule, nanomolar_factor

RULE = UnitNormalizationRule()


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("1.5", "uM", 1500.0),
        ("2", "µM", 2000.0),
        ("3", "nM", 3.0),
        ("500", "pM", 0.5),
        ("1e-6", "M", 1000.0),
        ("7", " NM ", 7.0),
    ],
)
def test_conversions(value: str, unit: str, expected: float) -> None:
    r = raw(activity_value=value, activity_unit=unit)
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    assert outcome.record.activity_value_nm == pytest.approx(expected)
    assert outcome.record.activity_relation == "="


def test_relation_operator_preserved() -> None:
    r = raw(activity_value="5", activity_unit="nM", activity_relation="<")
    outcome = RULE.apply(r, seed(r))
    assert outcome.record.activity_relation == "<"


def test_bad_relation_operator_is_error() -> None:
    r = raw(activity_value="5", activity_unit="nM", activity_relation="~=")
    [issue] = RULE.apply(r, seed(r)).issues
    assert issue.field == "activity_relation"


def test_lowercase_m_is_ambiguous() -> None:
    assert nanomolar_factor("m") is None
    assert nanomolar_factor("M") == 1e9


@pytest.mark.parametrize(
    ("value", "unit", "field"),
    [
        ("abc", "nM", "activity_value"),
        ("-5", "nM", "activity_value"),
        ("7", None, "activity_unit"),
        ("5", "furlongs", "activity_unit"),
    ],
)
def test_errors(value: str, unit: str | None, field: str) -> None:
    r = raw(activity_value=value, activity_unit=unit)
    outcome = RULE.apply(r, seed(r))
    assert any(i.field == field and i.severity is Severity.ERROR for i in outcome.issues)


def test_no_activity_is_fine() -> None:
    assert RULE.apply(raw(), seed(raw())).issues == []


def test_unit_without_value_warns() -> None:
    r = raw(activity_unit="nM")
    [issue] = RULE.apply(r, seed(r)).issues
    assert issue.severity is Severity.WARNING
