"""PubChem PUG REST connector: compound properties for a list of CIDs.

Its property list, response model and :func:`fault_message` are also used by
structure resolution (``ingestion/resolution.py``), which looks compounds up
by InChIKey, CID or name.
"""

import time
from collections.abc import AsyncIterator, Callable, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import RawRecord, SourceSpec, SourceType
from dndlabs.ingestion.http import RETRYABLE_STATUS, RetryPolicy, send_with_retries

logger = get_logger(__name__)

#: Properties requested from PUG REST. ``SMILES``/``ConnectivitySMILES`` are
#: PubChem's current names; :class:`PubChemProperties` also accepts the older
#: ``IsomericSMILES``/``CanonicalSMILES`` keys should a response carry them.
PROPERTIES = ("Title", "MolecularFormula", "MolecularWeight", "SMILES", "ConnectivitySMILES",
              "InChI", "InChIKey")  # fmt: skip


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

        Connectivity (canonical) SMILES drops stereochemistry, so it is the
        last resort.

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


def _chunks(items: Sequence[str], size: int) -> list[Sequence[str]]:
    """Split ``items`` into successive ``size``-long slices."""
    return [items[start : start + size] for start in range(0, len(items), size)]


class PubChemConnector:
    """Fetches compound properties from PubChem by CID.

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
        min_interval_seconds: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the connector.

        Args:
            client: HTTP client whose ``base_url`` points at PUG REST.
            batch_size: Maximum CIDs per request.
            max_retries: Retries for transient failures.
            backoff_seconds: Initial retry delay, doubled after each attempt.
            min_interval_seconds: Pause between batch requests
                (``Settings.pubchem_min_interval_seconds``; the default keeps
                to PubChem's published 5 requests per second).
            sleep: Sleep function (injectable for tests).
        """
        self._client = client
        self._batch_size = batch_size
        self._min_interval = min_interval_seconds
        self._retry = RetryPolicy(max_retries, backoff_seconds, sleep)

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Fetch compounds listed in ``spec`` by CID.

        Args:
            spec: A PubChem source spec.

        Yields:
            Raw records in PubChem response order.

        Raises:
            IngestionError: On non-retryable HTTP errors, exhausted retries or
                malformed responses.
        """
        if spec.source is not SourceType.PUBCHEM:
            raise IngestionError(f"PubChemConnector cannot fetch {spec.source.value!r}")
        # De-duplicate (keeping order) so a repeated CID costs no extra request.
        cids = list(dict.fromkeys(i.strip() for i in spec.identifiers if i.strip()))
        # CIDs travel comma-joined in the URL path, so the batch size bounds the
        # URL length and the number of requests. Batches are sent one after
        # another with a pause between them, as in resolution.py: a large CID
        # list would otherwise exceed PubChem's rate limit and be answered 503.
        for index, batch in enumerate(_chunks(cids, self._batch_size)):
            if index:
                self._retry.sleep(self._min_interval)
            path = f"/compound/cid/{','.join(batch)}/property/{','.join(PROPERTIES)}/JSON"
            for record in self._get_properties(path):
                yield record

    def _get_properties(self, path: str) -> list[RawRecord]:
        """GET a property endpoint and parse the result."""
        response = self._request(path)
        if response.is_error:
            raise IngestionError(
                f"PubChem request failed ({response.status_code}): {fault_message(response)}"
            )
        try:
            parsed = _PropertyResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise IngestionError(f"unexpected PubChem response shape: {exc}") from exc
        return [p.to_raw_record() for p in parsed.PropertyTable.Properties]

    def _request(self, path: str) -> httpx.Response:
        """GET with retries on transient errors.

        A retryable status that survives every retry is raised here with an
        "unavailable" message, so a busy PubChem is not reported as a bad request.
        """
        response = send_with_retries(lambda: self._client.get(path), "PubChem", self._retry)
        if response.status_code in RETRYABLE_STATUS:
            raise IngestionError(
                f"PubChem unavailable after {self._retry.max_retries + 1} attempts "
                f"({response.status_code}): {fault_message(response)}"
            )
        return response


def fault_message(response: httpx.Response) -> str:
    """Extract the PUG REST ``Fault`` message, falling back to the body text.

    Args:
        response: A PUG REST error response.

    Returns:
        The fault's message (or code), else the first 200 characters of the body.
    """
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
        # A descriptive User-Agent lets the public service's operators tell
        # this platform's traffic apart.
        headers={"User-Agent": "dndlabs/0.1 (data-infrastructure platform)"},
        transport=transport,
    )
