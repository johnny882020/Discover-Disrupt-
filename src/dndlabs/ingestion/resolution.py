"""Structure resolution: a structure for records that identify it only indirectly.

A record with SMILES or InChI is left as it is. Otherwise its structure comes
from, in order:

1. a MOL block, read locally with RDKit;
2. its InChIKey, PubChem CID or name, looked up in PubChem (PUG REST);
3. its ChEMBL ID, looked up in ChEMBL.

Lookups are batched where the service allows it, de-duplicated, throttled to
PubChem's published rate (5 requests/s) and capped per run. A record that
cannot be resolved gets ``structure_error`` explaining why; validation turns
that into an issue. Nothing here raises for a bad record or an unavailable
service.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError
from rdkit import Chem

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import RawRecord
from dndlabs.ingestion.http import RetryPolicy, send_with_retries
from dndlabs.ingestion.pubchem import PROPERTIES, PubChemProperties, fault_message
from dndlabs.ingestion.tabular import mol_to_smiles

logger = get_logger(__name__)

_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
_CHEMBL_ID = re.compile(r"^CHEMBL\d+$")
#: Order in which a record's identifiers are tried.
_KINDS = ("inchikey", "pubchem_cid", "chembl_id", "lookup_name")
_PROPERTY_PATH = "property/" + ",".join(PROPERTIES) + "/JSON"


@dataclass(frozen=True)
class _Found:
    smiles: str
    title: str | None
    source: str


@dataclass(frozen=True)
class _Missing:
    reason: str


_Result = _Found | _Missing


class _PropertyTable(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    Properties: list[PubChemProperties]


class _PropertyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    PropertyTable: _PropertyTable


class _ChemblStructures(BaseModel):
    model_config = ConfigDict(extra="ignore")
    canonical_smiles: str | None = None


class _ChemblMolecule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    molecule_chembl_id: str
    pref_name: str | None = None
    molecule_structures: _ChemblStructures | None = None


class _MoleculeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    molecules: list[_ChemblMolecule]


class LookupStructureResolver:
    """Resolves structures from MOL blocks and from PubChem/ChEMBL lookups."""

    def __init__(
        self,
        pubchem: httpx.Client,
        chembl: httpx.Client,
        lookup_limit: int = 1000,
        batch_size: int = 100,
        throttle_seconds: float = 0.2,
        retry: RetryPolicy | None = None,
    ) -> None:
        """Create the resolver.

        Args:
            pubchem: HTTP client whose ``base_url`` points at PUG REST.
            chembl: HTTP client whose ``base_url`` points at the ChEMBL API.
            lookup_limit: Most distinct identifiers looked up per run; records
                beyond it are reported rather than resolved.
            batch_size: Identifiers per batched request (CIDs, ChEMBL IDs).
            throttle_seconds: Pause between PubChem requests.
            retry: Retry policy for transient failures.
        """
        self._pubchem = pubchem
        self._chembl = chembl
        self._limit = lookup_limit
        self._batch = batch_size
        self._throttle = throttle_seconds
        self._retry = retry or RetryPolicy()

    async def resolve(self, raws: Sequence[RawRecord]) -> list[RawRecord]:
        """Resolve structures; never raises for an unresolvable record.

        Args:
            raws: Records from a connector.

        Returns:
            The same records, in order, with ``smiles`` and
            ``structure_source`` filled in, or ``structure_error`` set.
        """
        records = list(raws)
        reasons: dict[int, list[str]] = {}
        pending: list[int] = []
        for index, raw in enumerate(records):
            if raw.smiles or raw.inchi:
                continue
            if raw.mol_block:
                mol = Chem.MolFromMolBlock(raw.mol_block, sanitize=False, removeHs=False)
                if mol is not None:
                    records[index] = raw.model_copy(update={"smiles": mol_to_smiles(mol)})
                    continue
                reasons.setdefault(index, []).append("the MOL block could not be read")
            if _identifiers(raw):
                pending.append(index)
        results: dict[tuple[str, str], _Result] = {}
        budget = self._limit
        for kind in _KINDS:
            wanted = [(i, v) for i in pending if (v := _identifier(records[i], kind)) is not None]
            new = list(dict.fromkeys(v for _, v in wanted if (kind, v) not in results))
            allowed, over = new[:budget], new[budget:]
            budget -= len(allowed)
            results.update(self._lookup(kind, allowed))
            for value in over:
                results[(kind, value)] = _Missing(
                    f"not looked up: over the limit of {self._limit} lookups per run"
                )
            still: list[int] = []
            for index in pending:
                identifier = _identifier(records[index], kind)
                if identifier is None:
                    still.append(index)
                    continue
                result = results[(kind, identifier)]
                if isinstance(result, _Found):
                    raw = records[index]
                    records[index] = raw.model_copy(
                        update={
                            "smiles": result.smiles,
                            "structure_source": result.source,
                            "name": raw.name or raw.lookup_name or result.title,
                        }
                    )
                else:
                    reasons.setdefault(index, []).append(result.reason)
                    still.append(index)
            pending = still
        for index, messages in reasons.items():
            if not (records[index].smiles or records[index].inchi):
                records[index] = records[index].model_copy(
                    update={"structure_error": "; ".join(messages)}
                )
        return records

    def _lookup(self, kind: str, values: list[str]) -> dict[tuple[str, str], _Result]:
        """Look up distinct identifiers of one kind."""
        if not values:
            return {}
        if kind == "pubchem_cid":
            return self._lookup_cids(values)
        if kind == "chembl_id":
            return self._lookup_chembl(values)
        return {(kind, value): self._lookup_one(kind, value) for value in values}

    def _lookup_cids(self, values: list[str]) -> dict[tuple[str, str], _Result]:
        """Look up PubChem CIDs, batched."""
        results: dict[tuple[str, str], _Result] = {}
        valid = [v for v in values if v.isdigit()]
        for value in values:
            if not value.isdigit():
                results[("pubchem_cid", value)] = _Missing(f"{value!r} is not a PubChem CID")
        for start in range(0, len(valid), self._batch):
            batch = valid[start : start + self._batch]
            path = f"/compound/cid/{','.join(batch)}/{_PROPERTY_PATH}"
            found = self._pubchem_properties(partial(self._pubchem.get, path))
            if isinstance(found, _Missing):
                results.update({("pubchem_cid", v): found for v in batch})
                continue
            by_cid = {p.cid: p for p in found}
            for value in batch:
                entry = by_cid.get(int(value))
                smiles = entry.best_smiles() if entry else None
                results[("pubchem_cid", value)] = (
                    _Found(smiles, entry.title if entry else None, f"PubChem CID {value}")
                    if smiles
                    else _Missing(f"PubChem has no compound with CID {value}")
                )
        return results

    def _lookup_one(self, kind: str, value: str) -> _Result:
        """Look up one InChIKey or name in PubChem."""
        if kind == "inchikey":
            key = value.upper()
            if not _INCHIKEY.match(key):
                return _Missing(f"{value!r} is not an InChIKey")
            field, label = "inchikey", f"InChIKey {key}"
            payload = key
        else:
            field, label = "name", f"name {value!r}"
            payload = value
        found = self._pubchem_properties(
            partial(
                self._pubchem.post, f"/compound/{field}/{_PROPERTY_PATH}", data={field: payload}
            )
        )
        if isinstance(found, _Missing):
            return found
        structures: dict[str, PubChemProperties] = {}
        for entry in sorted(found, key=lambda p: p.cid):
            smiles = entry.best_smiles()
            if smiles is not None:
                structures.setdefault(smiles, entry)
        if not structures:
            return _Missing(f"PubChem has no structure for {label}")
        if kind == "lookup_name" and len(structures) > 1:
            cids = ", ".join(str(p.cid) for p in list(structures.values())[:3])
            return _Missing(
                f"{label} matches {len(structures)} different PubChem compounds (CIDs {cids}…)"
            )
        smiles, entry = next(iter(structures.items()))
        return _Found(smiles, entry.title, f"PubChem {label} (CID {entry.cid})")

    def _pubchem_properties(
        self, send: Callable[[], httpx.Response]
    ) -> list[PubChemProperties] | _Missing:
        """Send one PubChem request (throttled); parse its property table."""
        self._retry.sleep(self._throttle)
        try:
            response = send_with_retries(send, "PubChem", self._retry)
        except IngestionError:
            return _Missing("PubChem is unreachable; try the run again later")
        if response.status_code == 404:
            return _Missing(f"not found in PubChem ({fault_message(response)})")
        if response.is_error:
            return _Missing(f"PubChem lookup failed ({response.status_code})")
        try:
            return _PropertyResponse.model_validate_json(response.content).PropertyTable.Properties
        except ValidationError:
            return _Missing("unexpected response from PubChem")

    def _lookup_chembl(self, values: list[str]) -> dict[tuple[str, str], _Result]:
        """Look up ChEMBL molecule IDs, batched."""
        results: dict[tuple[str, str], _Result] = {}
        valid = [v for v in values if _CHEMBL_ID.match(v.upper())]
        for value in values:
            if value not in valid:
                results[("chembl_id", value)] = _Missing(f"{value!r} is not a ChEMBL ID")
        for start in range(0, len(valid), self._batch):
            batch = valid[start : start + self._batch]
            ids = ",".join(v.upper() for v in batch)
            params: dict[str, str | int] = {"molecule_chembl_id__in": ids, "limit": len(batch)}
            try:
                response = send_with_retries(
                    partial(self._chembl.get, "/molecule.json", params=params),
                    "ChEMBL",
                    self._retry,
                )
                response.raise_for_status()
                molecules = _MoleculeResponse.model_validate_json(response.content).molecules
            except IngestionError:
                missing = _Missing("ChEMBL is unreachable; try the run again later")
                results.update({("chembl_id", v): missing for v in batch})
                continue
            except (httpx.HTTPStatusError, ValidationError):
                missing = _Missing("ChEMBL lookup failed")
                results.update({("chembl_id", v): missing for v in batch})
                continue
            by_id = {m.molecule_chembl_id: m for m in molecules}
            for value in batch:
                molecule = by_id.get(value.upper())
                smiles = (
                    molecule.molecule_structures.canonical_smiles
                    if molecule and molecule.molecule_structures
                    else None
                )
                if molecule is None:
                    results[("chembl_id", value)] = _Missing(f"ChEMBL has no molecule {value}")
                elif smiles is None:
                    results[("chembl_id", value)] = _Missing(
                        f"ChEMBL {value} has no small-molecule structure"
                    )
                else:
                    results[("chembl_id", value)] = _Found(
                        smiles, molecule.pref_name, f"ChEMBL {value.upper()}"
                    )
        return results


def _identifier(raw: RawRecord, kind: str) -> str | None:
    """The record's identifier of ``kind``, if any."""
    value: str | None = getattr(raw, kind)
    return value.strip() if value and value.strip() else None


def _identifiers(raw: RawRecord) -> bool:
    """Whether the record carries any identifier that can be looked up."""
    return any(_identifier(raw, kind) for kind in _KINDS)
