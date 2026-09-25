from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PUBCHEM_12_CIDS = [
    "2244", "3672", "5090", "2519", "1983", "4091",
    "2662", "3386", "156391", "3033", "4485", "3825",
]  # fmt: skip


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
