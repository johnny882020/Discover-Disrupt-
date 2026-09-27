from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from rdkit import Chem

from dndlabs.core.exceptions import RunInterruptedError
from dndlabs.core.schemas import RawRecord, SourceType
from dndlabs.ingestion.http import RetryPolicy
from dndlabs.ingestion.resolution import LookupStructureResolver

FIXTURES = Path(__file__).parents[2] / "fixtures"
ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"
ASPIRIN_KEY = "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

Handler = Callable[[httpx.Request], httpx.Response]


def _fixture(*parts: str) -> bytes:
    return FIXTURES.joinpath(*parts).read_bytes()


def _raw(index: int = 1, **fields: str) -> RawRecord:
    return RawRecord(source=SourceType.UPLOAD, source_record_id=f"row-{index}", **fields)


def _pubchem(request: httpx.Request) -> httpx.Response:
    """PUG REST, answering from fixtures."""
    path = request.url.path
    if path.startswith("/compound/cid/"):
        return httpx.Response(200, content=_fixture("pubchem", "properties_3.json"))
    form = parse_qs(request.content.decode())
    if path.startswith("/compound/inchikey/") and form.get("inchikey") == [ASPIRIN_KEY]:
        return httpx.Response(200, content=_fixture("pubchem", "name_aspirin.json"))
    if path.startswith("/compound/name/"):
        name = form["name"][0]
        if name == "aspirin":
            return httpx.Response(200, content=_fixture("pubchem", "name_aspirin.json"))
        if name == "glucose":
            return httpx.Response(200, content=_fixture("pubchem", "name_ambiguous.json"))
    return httpx.Response(404, content=_fixture("pubchem", "not_found.json"))


def _chembl(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/molecule.json"
    return httpx.Response(200, content=_fixture("chembl", "molecules.json"))


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request {request.url}")


def _resolver(
    pubchem: Handler = _pubchem,
    chembl: Handler = _chembl,
    sleeps: list[float] | None = None,
    **kwargs: float,
) -> LookupStructureResolver:
    recorded = sleeps if sleeps is not None else []
    return LookupStructureResolver(
        httpx.Client(base_url="https://pubchem.test", transport=httpx.MockTransport(pubchem)),
        httpx.Client(base_url="https://chembl.test", transport=httpx.MockTransport(chembl)),
        retry=RetryPolicy(max_retries=1, backoff_seconds=0, sleep=recorded.append),
        **kwargs,
    )


async def test_records_with_smiles_or_inchi_are_untouched() -> None:
    raws = [_raw(1, smiles="CCO", pubchem_cid="2244"), _raw(2, inchi="InChI=1S/CH4/h1H4")]
    resolved = await _resolver(_unexpected, _unexpected).resolve(raws)
    assert resolved == raws


async def test_mol_block_is_read_locally() -> None:
    block = Chem.MolToMolBlock(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
    assert block.startswith("\n")  # RDKit's blank title line must survive
    [record] = await _resolver(_unexpected, _unexpected).resolve([_raw(mol_block=block)])
    assert record.smiles == "CC(=O)Oc1ccccc1C(=O)O"
    assert (record.structure_source, record.structure_error) == (None, None)


async def test_unreadable_mol_block_is_reported() -> None:
    [record] = await _resolver(_unexpected, _unexpected).resolve([_raw(mol_block="garbage")])
    assert record.smiles is None
    assert record.structure_error == "the MOL block could not be read"


async def test_cids_are_batched_deduplicated_and_named() -> None:
    requests: list[str] = []

    def pubchem(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return _pubchem(request)

    raws = [_raw(1, pubchem_cid="2244"), _raw(2, pubchem_cid="3672"), _raw(3, pubchem_cid="2244")]
    resolved = await _resolver(pubchem).resolve(raws)

    assert len(requests) == 1 and requests[0].startswith("/compound/cid/2244,3672/")
    assert [r.smiles for r in resolved] == [ASPIRIN, "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O", ASPIRIN]
    assert resolved[0].structure_source == "PubChem CID 2244"
    assert resolved[0].name == "Aspirin"  # the record had no name of its own


async def test_bad_and_unknown_cids_are_explained() -> None:
    resolved = await _resolver().resolve([_raw(1, pubchem_cid="abc"), _raw(2, pubchem_cid="999")])
    assert resolved[0].structure_error == "'abc' is not a PubChem CID"
    assert resolved[1].structure_error == "PubChem has no compound with CID 999"


async def test_inchikey_lookup() -> None:
    resolved = await _resolver().resolve(
        [_raw(1, inchikey=ASPIRIN_KEY.lower()), _raw(2, inchikey="not-a-key")]
    )
    assert resolved[0].smiles == ASPIRIN
    assert resolved[0].structure_source == f"PubChem InChIKey {ASPIRIN_KEY} (CID 2244)"
    assert resolved[1].structure_error == "'not-a-key' is not an InChIKey"


async def test_name_lookup_keeps_the_given_name() -> None:
    [record] = await _resolver().resolve([_raw(lookup_name="aspirin", name="ASA-7")])
    assert record.smiles == ASPIRIN
    assert record.name == "ASA-7"
    assert record.structure_source == "PubChem name 'aspirin' (CID 2244)"


async def test_ambiguous_and_unknown_names_are_rejected() -> None:
    resolved = await _resolver().resolve(
        [_raw(1, lookup_name="glucose"), _raw(2, lookup_name="unknownium")]
    )
    assert resolved[0].smiles is None
    assert resolved[0].structure_error is not None
    assert "matches 2 different PubChem compounds (CIDs 5793, 107526" in resolved[0].structure_error
    assert resolved[1].structure_error == "not found in PubChem (No CID found)"


async def test_chembl_ids() -> None:
    resolved = await _resolver().resolve(
        [
            _raw(1, chembl_id="chembl25"),
            _raw(2, chembl_id="CHEMBL1201580"),
            _raw(3, chembl_id="CHEMBL999999"),
            _raw(4, chembl_id="25"),
        ]
    )
    assert resolved[0].smiles == "CC(=O)Oc1ccccc1C(=O)O"
    assert resolved[0].structure_source == "ChEMBL CHEMBL25"
    assert resolved[0].name == "ASPIRIN"
    assert resolved[1].structure_error == "ChEMBL CHEMBL1201580 has no small-molecule structure"
    assert resolved[2].structure_error == "ChEMBL has no molecule CHEMBL999999"
    assert resolved[3].structure_error == "'25' is not a ChEMBL ID"


async def test_next_identifier_is_tried_when_one_fails() -> None:
    [record] = await _resolver().resolve(
        [_raw(inchikey="AAAAAAAAAAAAAA-BBBBBBBBBB-N", chembl_id="CHEMBL25")]
    )
    assert record.structure_source == "ChEMBL CHEMBL25"
    assert record.structure_error is None


async def test_every_reason_is_kept_when_nothing_resolves() -> None:
    [record] = await _resolver().resolve([_raw(mol_block="garbage", pubchem_cid="999")])
    assert record.structure_error == (
        "the MOL block could not be read; PubChem has no compound with CID 999"
    )


async def test_unavailable_services_never_raise() -> None:
    def busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    resolved = await _resolver(busy, down).resolve(
        [_raw(1, pubchem_cid="2244"), _raw(2, chembl_id="CHEMBL25")]
    )
    assert resolved[0].structure_error == "PubChem lookup failed (503)"
    assert resolved[1].structure_error == "ChEMBL is unreachable; try the run again later"


async def test_lookups_are_capped_per_run() -> None:
    resolved = await _resolver(lookup_limit=1).resolve(
        [_raw(1, pubchem_cid="2244"), _raw(2, lookup_name="aspirin")]
    )
    assert resolved[0].smiles == ASPIRIN
    assert resolved[1].structure_error == "not looked up: over the limit of 1 lookups per run"


async def test_pubchem_requests_are_throttled() -> None:
    sleeps: list[float] = []
    await _resolver(sleeps=sleeps).resolve(
        [_raw(1, lookup_name="aspirin"), _raw(2, inchikey=ASPIRIN_KEY)]
    )
    assert sleeps == [0.2, 0.2]


async def test_pubchem_interval_is_configurable() -> None:
    sleeps: list[float] = []
    await _resolver(sleeps=sleeps, min_interval_seconds=0.5).resolve(
        [_raw(1, lookup_name="aspirin"), _raw(2, inchikey=ASPIRIN_KEY)]
    )
    assert sleeps == [0.5, 0.5]


@pytest.mark.parametrize("value", ["", "   "])
async def test_blank_identifiers_are_ignored(value: str) -> None:
    [record] = await _resolver(_unexpected, _unexpected).resolve([_raw(pubchem_cid=value)])
    assert (record.smiles, record.structure_error) == (None, None)


async def test_checkpoint_reports_records_resolved_after_each_lookup() -> None:
    block = Chem.MolToMolBlock(Chem.MolFromSmiles("CCO"))
    raws = [
        _raw(1, mol_block=block),  # resolved locally, before any lookup
        _raw(2, pubchem_cid="2244"),
        _raw(3, lookup_name="aspirin"),
        _raw(4, lookup_name="aspirin"),  # the same lookup resolves both records
        _raw(5, lookup_name="unknown"),
    ]
    reported: list[int] = []
    resolved = await _resolver().resolve(raws, reported.append)
    # One call per request: the CID batch, then each distinct name.
    assert reported == [2, 4, 4]
    assert sum(1 for r in resolved if r.smiles) == 4


async def test_what_the_checkpoint_raises_stops_resolution_at_once() -> None:
    requests: list[str] = []

    def counting(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return _pubchem(request)

    def stop(done: int) -> None:
        raise RunInterruptedError("shutting down")

    with pytest.raises(RunInterruptedError):  # not swallowed as a failed lookup
        await _resolver(counting).resolve(
            [_raw(i, lookup_name=name) for i, name in enumerate(["aspirin", "glucose", "x"])],
            stop,
        )
    assert len(requests) == 1
