from tests.unit.validation.helpers import ASPIRIN, raw, seed

from dndlabs.core.schemas import Severity
from dndlabs.validation.structure_source import StructureSourceRule


def test_supplied_structures_raise_no_issue() -> None:
    r = raw(smiles=ASPIRIN)
    assert StructureSourceRule().apply(r, seed(r)).issues == []


def test_looked_up_structure_is_flagged_with_its_source() -> None:
    r = raw(smiles=ASPIRIN, pubchem_cid="2244", structure_source="PubChem CID 2244")
    [issue] = StructureSourceRule().apply(r, seed(r)).issues
    assert issue.severity is Severity.WARNING
    assert (issue.rule, issue.message) == ("structure_lookup", "structure from PubChem CID 2244")


def test_failed_lookup_rejects_the_record_with_the_reason() -> None:
    r = raw(chembl_id="CHEMBL1", structure_error="ChEMBL has no molecule CHEMBL1")
    [issue] = StructureSourceRule().apply(r, seed(r)).issues
    assert issue.severity is Severity.ERROR
    assert issue.message == "ChEMBL has no molecule CHEMBL1"
