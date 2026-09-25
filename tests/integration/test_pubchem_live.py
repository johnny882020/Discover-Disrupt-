"""Opt-in checks against the live PubChem API (``DNDLABS_LIVE_TESTS=1``)."""

import json
import os

import httpx
import pytest

from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.ingestion.pubchem import PubChemConnector, build_pubchem_client
from dndlabs.validation.validator import Validator
from tests.conftest import FIXTURES, PUBCHEM_12_CIDS

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DNDLABS_LIVE_TESTS") != "1", reason="set DNDLABS_LIVE_TESTS=1"
    ),
]

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


def test_live_pubchem_matches_fixture() -> None:
    with build_pubchem_client(BASE, 30) as client:
        records = PubChemConnector(client).fetch(
            SourceSpec(source=SourceType.PUBCHEM, identifiers=PUBCHEM_12_CIDS)
        )
    assert [r.source_record_id for r in records] == PUBCHEM_12_CIDS
    fixture = json.loads((FIXTURES / "pubchem_properties_12.json").read_text())
    expected = {str(p["CID"]): p["InChIKey"] for p in fixture["PropertyTable"]["Properties"]}
    assert {r.source_record_id: r.inchikey for r in records} == expected
    outcome = Validator().run("live", records)
    assert outcome.report.accepted_records == 12


def test_live_pubchem_name_lookup() -> None:
    with httpx.Client(base_url=BASE, timeout=30) as client:
        records = PubChemConnector(client).fetch(
            SourceSpec(
                source=SourceType.PUBCHEM,
                identifiers=["aspirin", "definitely-not-a-compound-xyz"],
                identifier_type="name",
            )
        )
    assert [r.source_record_id for r in records] == ["2244"]
