"""Opt-in checks against the live ChEMBL API (``DNDLABS_LIVE_TESTS=1``)."""

import os

import pytest

from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.chembl import ChemblConnector, build_chembl_client

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DNDLABS_LIVE_TESTS") != "1", reason="set DNDLABS_LIVE_TESTS=1"
    ),
]

BASE = "https://www.ebi.ac.uk/chembl/api/data"


async def test_live_chembl_returns_activities_for_a_target() -> None:
    with build_chembl_client(BASE, 30) as client:
        connector = ChemblConnector(client, page_size=5)
        records = []
        async for record in connector.fetch(
            SourceSpec(source=SourceType.CHEMBL, chembl_target="CHEMBL204")
        ):
            records.append(record)
            if len(records) >= 5:
                break
    assert len(records) >= 1
