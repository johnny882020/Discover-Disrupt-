import pytest
from rdkit import Chem

from dndlabs.core.schemas import AlertFamily
from dndlabs.preprocessing.alerts import REACTIVE_METABOLITE_ALERTS, AlertScanner

SCANNER = AlertScanner()

#: Each reactive-metabolite alert with molecules that must and must not trigger it.
CASES: dict[str, tuple[list[str], list[str]]] = {
    "Aniline (primary aromatic amine)": (
        ["Nc1ccccc1", "CC(=O)Nc1ccc(N)cc1"],
        ["CC(=O)Nc1ccccc1", "NCc1ccccc1", "NC(=O)c1ccccc1"],
    ),
    "Nitroaromatic": (["O=[N+]([O-])c1ccccc1"], ["CC[N+](=O)[O-]"]),
    "Thiophene": (["Cc1cccs1"], ["C1CCSC1"]),
    "Furan": (["Cc1ccco1"], ["C1CCOC1"]),
    "Hydrazine or hydrazide": (["NNc1ccccc1", "CC(=O)NN"], ["c1cn[nH]c1", "CN=NC"]),
    "Michael acceptor (alpha,beta-unsaturated carbonyl)": (
        ["C=CC(=O)N", "CC=CC(=O)C"],
        ["CCC(=O)C", "CC(=O)c1ccccc1"],
    ),
    "Epoxide or aziridine": (["CC1CO1", "C1CN1"], ["C1COC1", "CCOC"]),
    "Quinone": (
        ["O=C1C=CC(=O)C=C1", "O=C1C(=O)c2ccccc2C=C1"],
        ["O=C1CCC(=O)CC1", "CC(=O)C(C)=O"],
    ),
    "Catechol or hydroquinone (quinone precursor)": (
        ["Oc1ccccc1O", "Oc1ccc(O)cc1"],
        ["Oc1cccc(O)c1", "COc1ccccc1O"],
    ),
    "Alkyl halide": (["CCCl", "CBr"], ["Clc1ccccc1", "CC(F)(F)F", "FC(F)(F)Cl"]),
    "Aldehyde": (["CC=O", "O=Cc1ccccc1"], ["CC(C)=O", "O=CO"]),
    "Thiourea": (["NC(N)=S", "CNC(=S)NC"], ["NC(N)=O", "CC(N)=S"]),
    "Terminal alkyne": (["C#CC", "C#Cc1ccccc1"], ["CC#CC"]),
    "Methylenedioxyphenyl": (["c1ccc2c(c1)OCO2"], ["c1ccc2c(c1)OCCO2"]),
    "2-Aminothiazole": (["Nc1nccs1", "CNc1ncc(C)s1"], ["c1cscn1", "CC(=O)c1nccs1"]),
}


def _reactive(smiles: str) -> set[str]:
    alerts = SCANNER.scan(Chem.MolFromSmiles(smiles))
    return {a.name for a in alerts if a.family is AlertFamily.REACTIVE_METABOLITE}


def test_every_reactive_metabolite_alert_is_covered() -> None:
    assert set(CASES) == set(REACTIVE_METABOLITE_ALERTS)


@pytest.mark.parametrize("name", sorted(CASES))
def test_reactive_metabolite_alert(name: str) -> None:
    positives, negatives = CASES[name]
    for smiles in positives:
        assert name in _reactive(smiles), smiles
    for smiles in negatives:
        assert name not in _reactive(smiles), smiles


def test_pains_and_brenk_catalogs_report_names_and_atoms() -> None:
    smiles = "S=C1SC(=Cc2ccccc2)C(=O)N1"  # a benzylidene rhodanine, a classic PAINS
    alerts = SCANNER.scan(Chem.MolFromSmiles(smiles))
    by_family = {a.family: a for a in alerts}
    assert by_family[AlertFamily.PAINS].name.startswith("ene_rhod")
    assert AlertFamily.BRENK in by_family
    mol = Chem.MolFromSmiles(smiles)
    assert all(0 <= i < mol.GetNumAtoms() for a in alerts for i in a.atoms)


def test_highlighted_atoms_are_the_matched_group() -> None:
    [alert] = [
        a for a in SCANNER.scan(Chem.MolFromSmiles("CCc1ccc(N)cc1")) if a.name.startswith("Aniline")
    ]
    mol = Chem.MolFromSmiles("CCc1ccc(N)cc1")
    assert {mol.GetAtomWithIdx(i).GetSymbol() for i in alert.atoms} == {"N", "C"}
    assert len(alert.atoms) == 2  # the amine and the ring carbon it sits on


def test_a_clean_molecule_has_no_alerts() -> None:
    assert SCANNER.scan(Chem.MolFromSmiles("CC(C)Cc1ccc(C(C)C(=O)O)cc1")) == []  # ibuprofen
