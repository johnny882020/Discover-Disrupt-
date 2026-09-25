import pytest
from tests.unit.validation.helpers import ASPIRIN, raw, seed

from dndlabs.core.schemas import Severity
from dndlabs.validation.schema import SchemaRule


def test_valid_record_passes_and_parses_weight() -> None:
    r = raw(smiles=ASPIRIN, molecular_weight="180.16")
    outcome = SchemaRule().apply(r, seed(r))
    assert outcome.issues == []
    assert outcome.record.molecular_weight == 180.16


def test_inchi_only_is_enough() -> None:
    r = raw(inchi="InChI=1S/CH4/h1H4")
    assert SchemaRule().apply(r, seed(r)).issues == []


def test_missing_identifiers_is_error() -> None:
    r = raw(name="nothing")
    [issue] = SchemaRule().apply(r, seed(r)).issues
    assert issue.severity is Severity.ERROR
    assert issue.field == "smiles"


@pytest.mark.parametrize("weight", ["heavy", "-3", "0", "nan"])
def test_bad_molecular_weight(weight: str) -> None:
    r = raw(smiles="C", molecular_weight=weight)
    outcome = SchemaRule().apply(r, seed(r))
    assert [i.field for i in outcome.issues] == ["molecular_weight"]
    assert outcome.record.molecular_weight is None


def test_thousands_separator_accepted() -> None:
    r = raw(smiles="C", molecular_weight="1,202.6")
    assert SchemaRule().apply(r, seed(r)).record.molecular_weight == 1202.6
