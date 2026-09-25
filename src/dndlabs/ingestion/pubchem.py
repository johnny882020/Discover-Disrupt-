"""PubChem PUG REST connector."""

import time
from collections.abc import Callable, Iterator, Sequence
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import IdentifierType, RawRecord, SourceSpec, SourceType

logger = get_logger(__name__)

#: Properties requested from PUG REST. ``SMILES``/``ConnectivitySMILES`` are the
#: current names; responses using the legacy keys are still understood.
PROPERTIES = (
    "Title",
    "MolecularFormula",
    "MolecularWeight",
    "SMILES",
    "ConnectivitySMILES",
    "InChI",
    "InChIKey",
)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class PubChemProperties(BaseModel):
    """One entry of a PUG REST ``PropertyTable`` response."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    cid: int = Field(alias="CID")
    title: str | None = Field(default=None, alias="Title")
    molecular_formula: str | None = Field(default=None, alias="MolecularFormula")
    molecular_weight: str | float | None = Field(default=None, alias="MolecularWeight")
    smiles: str | None = Field(default=None, alias="SMILES")
    isomeric_smiles: str | None = Field(default=None, alias="IsomericSMILES")
    canonical_smiles: str | None = Field(default=None, alias="CanonicalSMILES")
    connectivity_smiles: str | None = Field(default=None, alias="ConnectivitySMILES")
    inchi: str | None = Field(default=None, alias="InChI")
    inchikey: str | None = Field(default=None, alias="InChIKey")

    def best_smiles(self) -> str | None:
        """Return the most specific SMILES available (isomeric first).

        Returns:
            A SMILES string or ``None``.
        """
        return (
            self.smiles or self.isomeric_smiles or self.canonical_smiles or self.connectivity_smiles
        )

    def to_raw_record(self) -> RawRecord:
        """Convert to the shared ``RawRecord`` contract.

        Returns:
            The raw record.
        """
        return RawRecord(
            source=SourceType.PUBCHEM,
            source_record_id=str(self.cid),
            name=self.title,
            smiles=self.best_smiles(),
            inchi=self.inchi,
            inchikey=self.inchikey,
            molecular_formula=self.molecular_formula,
            molecular_weight=self.molecular_weight,
            extra={"pubchem_cid": self.cid},
        )


class _PropertyTable(BaseModel):
    """``PropertyTable`` wrapper."""

    Properties: list[PubChemProperties]


class _PropertyResponse(BaseModel):
    """Top-level PUG REST property response."""

    PropertyTable: _PropertyTable


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    """Yield successive ``size``-long slices of ``items``."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


class PubChemConnector:
    """Fetches compound properties from PubChem by CID or by name.

    Attributes:
        source: Always :attr:`SourceType.PUBCHEM`.
    """

    source = SourceType.PUBCHEM

    def __init__(
        self,
        client: httpx.Client,
        batch_size: int = 100,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the connector.

        Args:
            client: HTTP client whose ``base_url`` points at PUG REST.
            batch_size: Maximum CIDs per request.
            max_retries: Retries for transient failures.
            backoff_seconds: Initial retry delay, doubled after each attempt.
            sleep: Sleep function (injectable for tests).
        """
        self._client = client
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._sleep = sleep

    def fetch(self, spec: SourceSpec) -> list[RawRecord]:
        """Fetch compounds listed in ``spec``.

        Args:
            spec: A PubChem source spec.

        Returns:
            Raw records in PubChem response order.

        Raises:
            IngestionError: On non-retryable HTTP errors, exhausted retries or
                malformed responses.
        """
        if spec.source is not SourceType.PUBCHEM:
            raise IngestionError(f"PubChemConnector cannot fetch {spec.source.value!r}")
        identifiers = list(dict.fromkeys(i.strip() for i in spec.identifiers if i.strip()))
        if spec.identifier_type is IdentifierType.CID:
            records = self._fetch_cids(identifiers)
        else:
            records = self._fetch_names(identifiers)
        logger.info(
            "pubchem fetch complete",
            extra={"requested": len(identifiers), "received": len(records)},
        )
        return records

    def _fetch_cids(self, cids: Sequence[str]) -> list[RawRecord]:
        """Fetch CIDs in batches."""
        records: list[RawRecord] = []
        for batch in _chunks(cids, self._batch_size):
            path = f"/compound/cid/{','.join(batch)}/property/{','.join(PROPERTIES)}/JSON"
            records.extend(self._get_properties(path, allow_not_found=False))
        return records

    def _fetch_names(self, names: Sequence[str]) -> list[RawRecord]:
        """Fetch names one request at a time (PUG REST resolves one name per call)."""
        records: list[RawRecord] = []
        for name in names:
            path = f"/compound/name/{quote(name, safe='')}/property/{','.join(PROPERTIES)}/JSON"
            found = self._get_properties(path, allow_not_found=True)
            if not found:
                logger.warning("pubchem name not found", extra={"compound_name": name})
            records.extend(found)
        return records

    def _get_properties(self, path: str, allow_not_found: bool) -> list[RawRecord]:
        """GET a property endpoint and parse the result."""
        response = self._request(path)
        if response.status_code == 404 and allow_not_found:
            return []
        if response.is_error:
            raise IngestionError(
                f"PubChem request failed ({response.status_code}): {_fault_message(response)}"
            )
        try:
            parsed = _PropertyResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise IngestionError(f"unexpected PubChem response shape: {exc}") from exc
        return [p.to_raw_record() for p in parsed.PropertyTable.Properties]

    def _request(self, path: str) -> httpx.Response:
        """GET with retries on transient errors."""
        delay = self._backoff
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(path)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise IngestionError(f"PubChem unreachable: {exc}") from exc
                logger.warning("pubchem transport error, retrying", extra={"error": str(exc)})
            else:
                if response.status_code not in _RETRYABLE_STATUS:
                    return response
                if attempt == self._max_retries:
                    raise IngestionError(
                        f"PubChem unavailable after {attempt + 1} attempts "
                        f"({response.status_code}): {_fault_message(response)}"
                    )
                logger.warning(
                    "pubchem busy, retrying", extra={"status_code": response.status_code}
                )
            self._sleep(delay)
            delay *= 2
        raise IngestionError("unreachable retry state")  # pragma: no cover


def _fault_message(response: httpx.Response) -> str:
    """Extract the PUG REST ``Fault`` message, falling back to the body text."""
    try:
        fault = response.json().get("Fault", {})
        return str(fault.get("Message") or fault.get("Code") or response.text[:200])
    except ValueError:
        return response.text[:200]


def build_pubchem_client(
    base_url: str, timeout_seconds: float, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Create an HTTP client configured for PUG REST.

    Args:
        base_url: PUG REST base URL.
        timeout_seconds: Request timeout.
        transport: Optional transport override (tests, fixture recording).

    Returns:
        A configured ``httpx.Client``.
    """
    return httpx.Client(
        base_url=base_url,
        timeout=timeout_seconds,
        headers={"User-Agent": "dndlabs/0.1 (data-infrastructure MVP)"},
        transport=transport,
    )
