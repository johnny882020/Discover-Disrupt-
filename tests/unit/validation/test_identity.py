from dndlabs.core.schemas import Severity
from dndlabs.validation.chem import from_inchi, from_smiles
from dndlabs.validation.identity import CompoundIdentityRule
from tests.unit.validation.helpers import (
    ASPIRIN,
    ASPIRIN_INCHI,
    ASPIRIN_KEY,
    CAFFEINE,
    CAFFEINE_AROMATIC,
    raw,
    seed,
)

RULE = CompoundIdentityRule()


def test_smiles_is_canonicalized_and_key_derived() -> None:
    r = raw(smiles=ASPIRIN)
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    rec = outcome.record
    assert rec.record_key == ASPIRIN_KEY
    assert rec.inchikey == ASPIRIN_KEY
    assert rec.inchi == ASPIRIN_INCHI
    assert rec.molecular_formula == "C9H8O4"
    assert rec.molecular_weight == 180.159
    assert rec.canonical_smiles == "CC(=O)Oc1ccccc1C(=O)O"


def test_equivalent_smiles_share_key() -> None:
    a, b = raw(smiles=CAFFEINE), raw(smiles=CAFFEINE_AROMATIC)
    assert RULE.apply(a, seed(a)).record.record_key == RULE.apply(b, seed(b)).record.record_key


def test_inchi_only() -> None:
    r = raw(inchi=ASPIRIN_INCHI)
    assert RULE.apply(r, seed(r)).record.record_key == ASPIRIN_KEY


def test_invalid_smiles_is_error() -> None:
    r = raw(smiles="C1CC(")
    outcome = RULE.apply(r, seed(r))
    [issue] = outcome.issues
    assert issue.severity is Severity.ERROR
    assert issue.field == "smiles"
    assert outcome.record.record_key is None


def test_invalid_inchi_is_error() -> None:
    r = raw(inchi="InChI=garbage")
    [issue] = RULE.apply(r, seed(r)).issues
    assert issue.field == "inchi"


def test_smiles_inchi_mismatch_is_error() -> None:
    r = raw(smiles="CCO", inchi="InChI=1S/CH4O/c1-2/h2H,1H3")
    outcome = RULE.apply(r, seed(r))
    [issue] = outcome.issues
    assert issue.severity is Severity.ERROR
    assert "different compounds" in issue.message


def test_matching_smiles_and_inchi_ok() -> None:
    r = raw(smiles=ASPIRIN, inchi=ASPIRIN_INCHI)
    assert RULE.apply(r, seed(r)).issues == []


def test_claimed_key_and_formula_mismatch_warn() -> None:
    r = raw(smiles=ASPIRIN, inchikey="AAAAAAAAAAAAAA-UHFFFAOYSA-N", molecular_formula="C9H9O4")
    outcome = RULE.apply(r, seed(r))
    assert {i.field for i in outcome.issues} == {"inchikey", "molecular_formula"}
    assert all(i.severity is Severity.WARNING for i in outcome.issues)
    assert outcome.record.record_key == ASPIRIN_KEY
    assert outcome.record.molecular_formula == "C9H8O4"


def test_claimed_values_match_case_insensitively() -> None:
    r = raw(smiles=ASPIRIN, inchikey=ASPIRIN_KEY.lower(), molecular_formula="C9H8O4")
    assert RULE.apply(r, seed(r)).issues == []


def test_no_identifiers_is_left_to_schema_rule() -> None:
    r = raw()
    outcome = RULE.apply(r, seed(r))
    assert outcome.issues == []
    assert outcome.record.record_key is None


def test_keeps_parsed_weight() -> None:
    r = raw(smiles=ASPIRIN)
    outcome = RULE.apply(r, seed(r).model_copy(update={"molecular_weight": 180.16}))
    assert outcome.record.molecular_weight == 180.16


def test_chem_wrappers() -> None:
    assert from_smiles("not a smiles") is None
    assert from_inchi("nope") is None
    mol = from_smiles(" CCO ")
    assert mol is not None and mol.formula == "C2H6O"
