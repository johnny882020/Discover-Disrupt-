"""Opt-in checks of structure lookups against live PubChem and ChEMBL (``DNDLABS_LIVE_TESTS=1``).

They confirm the request and response shapes the offline fixtures assume.
"""

import os

import pytest

from dndlabs.core.schemas import RawRecord, SourceType
from dndlabs.ingestion.chembl import build_chembl_client
from dndlabs.ingestion.pubchem import build_pubchem_client
from dndlabs.ingestion.resolution import LookupStructureResolver

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DNDLABS_LIVE_TESTS") != "1", reason="set DNDLABS_LIVE_TESTS=1"
    ),
]

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CHEMBL = "https://www.ebi.ac.uk/chembl/api/data"


async def test_live_lookups_find_aspirin_by_every_identifier() -> None:
    raws = [
        RawRecord(source=SourceType.UPLOAD, source_record_id=str(i), **{kind: value})
        for i, (kind, value) in enumerate(
            [
                ("pubchem_cid", "2244"),
                ("inchikey", "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"),
                ("lookup_name", "aspirin"),
                ("chembl_id", "CHEMBL25"),
            ]
        )
    ]
    with build_pubchem_client(PUBCHEM, 30) as pubchem, build_chembl_client(CHEMBL, 30) as chembl:
        resolved = await LookupStructureResolver(pubchem, chembl).resolve(raws)
    assert all(r.smiles and not r.structure_error for r in resolved), resolved
