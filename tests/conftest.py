from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ASPIRIN_SMILES = "CC(=O)OC1=CC=CC=C1C(=O)O"
ASPIRIN_INCHI = "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)"
ASPIRIN_KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
CAFFEINE_SMILES = "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"
CAFFEINE_AROMATIC = "Cn1cnc2c1c(=O)n(C)c(=O)n2C"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
