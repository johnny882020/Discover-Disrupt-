from tests.unit.validation.helpers import (
    ASPIRIN,
    ASPIRIN_KEY,
    CAFFEINE,
    CAFFEINE_AROMATIC,
    raw,
    seed,
)

from dndlabs.core.schemas import Severity
from dndlabs.validation.chem import from_inchi, from_smiles
from dndlabs.validation.identity import CompoundIdentityRule

RULE = CompoundIdentityRule()


def test_smiles_is_canonicalized_and_key_derived() -> None:
    r = raw(smiles=ASPIRIN)
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    rec = outcome.record
    assert rec.record_key == ASPIRIN_KEY
    assert rec.molecular_formula == "C9H8O4"
    assert rec.canonical_smiles == "CC(=O)Oc1ccccc1C(=O)O"


def test_equivalent_smiles_share_key() -> None:
    a, b = raw(smiles=CAFFEINE), raw(smiles=CAFFEINE_AROMATIC)
    assert RULE.apply(a, seed(a)).record.record_key == RULE.apply(b, seed(b)).record.record_key


def test_invalid_smiles_is_error() -> None:
    r = raw(smiles="C1CC(")
    outcome = RULE.apply(r, seed(r))
    [issue] = outcome.issues
    assert issue.severity is Severity.ERROR
    assert issue.field == "smiles"


def test_smiles_inchi_mismatch_is_error() -> None:
    r = raw(smiles="CCO", inchi="InChI=1S/CH4O/c1-2/h2H,1H3")
    [issue] = RULE.apply(r, seed(r)).issues
    assert issue.severity is Severity.ERROR
    assert "different compounds" in issue.message


def test_claimed_key_and_formula_mismatch_warn() -> None:
    r = raw(smiles=ASPIRIN, inchikey="AAAAAAAAAAAAAA-UHFFFAOYSA-N", molecular_formula="C9H9O4")
    outcome = RULE.apply(r, seed(r))
    assert {i.field for i in outcome.issues} == {"inchikey", "molecular_formula"}
    assert all(i.severity is Severity.WARNING for i in outcome.issues)
    assert outcome.record.molecular_formula == "C9H8O4"


def test_no_identifiers_is_left_to_schema_rule() -> None:
    r = raw()
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    assert outcome.record.record_key is None


def test_chem_wrappers() -> None:
    assert from_smiles("not a smiles") is None
    assert from_inchi("nope") is None
    mol = from_smiles(" CCO ")
    assert mol is not None and mol.formula == "C2H6O"
