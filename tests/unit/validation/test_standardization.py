import uuid

from tests.unit.validation.helpers import ASPIRIN, ASPIRIN_KEY, raw, seed

from dndlabs.core.schemas import RawRecord, RuleOutcome, Severity, SourceType
from dndlabs.validation.identity import CompoundIdentityRule
from dndlabs.validation.standardization import StandardizationRule
from dndlabs.validation.validator import Validator

IDENTITY = CompoundIdentityRule()
RULE = StandardizationRule()


def _standardize(smiles: str) -> RuleOutcome:
    r = raw(smiles=smiles)
    identified = IDENTITY.apply(r, seed(r)).record
    return RULE.apply(r, identified)


def test_already_standard_structure_is_unchanged() -> None:
    outcome = _standardize(ASPIRIN)
    assert outcome.issues == []
    assert outcome.record.record_key == ASPIRIN_KEY


def test_salt_is_stripped_and_identifiers_recomputed() -> None:
    outcome = _standardize("CCN.Cl")  # ethylamine hydrochloride
    record = outcome.record
    assert record.canonical_smiles == "CCN"
    assert record.molecular_formula == "C2H7N"
    assert record.molecular_weight == 45.085
    assert record.record_key == record.inchikey
    [issue] = outcome.issues
    assert issue.severity is Severity.WARNING
    assert issue.rule == "standardization"
    assert "CCN.Cl" in issue.message  # the structure as submitted is kept in the report


def test_charges_are_neutralized() -> None:
    outcome = _standardize("O=C([O-])c1ccccc1")
    assert outcome.record.canonical_smiles == "O=C(O)c1ccccc1"


def test_mixture_is_kept_with_a_warning() -> None:
    outcome = _standardize("c1ccccc1.c1ccncc1")
    assert outcome.record.canonical_smiles == "c1ccccc1.c1ccncc1"
    [issue] = outcome.issues
    assert "2 components" in issue.message


def test_record_without_structure_passes_through() -> None:
    r = raw(smiles="C1CC(")
    rejected = IDENTITY.apply(r, seed(r)).record
    outcome = RULE.apply(r, rejected)
    assert outcome.record == rejected
    assert outcome.issues == []


def test_salt_forms_of_one_compound_are_deduplicated() -> None:
    records = [
        RawRecord(
            source=SourceType.CSV, source_record_id="free-base", smiles="CN1CCC[C@H]1c1cccnc1"
        ),
        RawRecord(
            source=SourceType.CSV,
            source_record_id="sulfate",
            smiles="CN1CCC[C@H]1c1cccnc1.OS(=O)(=O)O",
        ),
    ]
    outcome = Validator().run(uuid.uuid4(), uuid.uuid4(), records)
    assert [r.source_record_id for r in outcome.accepted] == ["free-base"]
    assert outcome.report.duplicate_records == 1
