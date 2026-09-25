"""Opt-in checks against the live PubChem API (``DNDLABS_LIVE_TESTS=1``)."""

import os

import pytest

from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.pubchem import PubChemConnector, build_pubchem_client

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DNDLABS_LIVE_TESTS") != "1", reason="set DNDLABS_LIVE_TESTS=1"
    ),
]

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


async def test_live_pubchem_matches_expected_aspirin() -> None:
    with build_pubchem_client(BASE, 30) as client:
        records = [
            r
            async for r in PubChemConnector(client).fetch(
                SourceSpec(source=SourceType.PUBCHEM, identifiers=["2244"])
            )
        ]
    assert records[0].inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
