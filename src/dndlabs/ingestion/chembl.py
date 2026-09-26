"""ChEMBL REST API connector: bioactivity data for a target."""

import time
from collections.abc import AsyncIterator, Callable

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import RawRecord, SourceSpec, SourceType

logger = get_logger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ChemblActivity(BaseModel):
    """One entry of a ChEMBL ``/activity.json`` response."""

    model_config = ConfigDict(extra="ignore")

    activity_id: int | None = None
    molecule_chembl_id: str
    canonical_smiles: str | None = None
    standard_type: str | None = None
    standard_value: str | float | None = None
    standard_units: str | None = None
    standard_relation: str | None = None
    target_chembl_id: str | None = None

    def to_raw_record(self) -> RawRecord:
        """Convert to the shared ``RawRecord`` contract.

        Returns:
            The raw record.
        """
        return RawRecord(
            source=SourceType.CHEMBL,
            source_record_id=self.molecule_chembl_id,
            smiles=self.canonical_smiles,
            assay_type=self.standard_type,
            activity_value=self.standard_value,
            activity_unit=self.standard_units,
            activity_relation=self.standard_relation,
            target=self.target_chembl_id,
            extra={"activity_id": self.activity_id} if self.activity_id is not None else {},
        )


class _PageMeta(BaseModel):
    """ChEMBL pagination metadata."""

    limit: int
    offset: int
    total_count: int
    next: str | None = None


class _ActivityResponse(BaseModel):
    """Top-level ChEMBL activity response."""

    activities: list[ChemblActivity]
    page_meta: _PageMeta


class ChemblConnector:
    """Fetches bioactivity records from the ChEMBL REST API by target.

    Attributes:
        source: Always :attr:`SourceType.CHEMBL`.
    """

    source = SourceType.CHEMBL

    def __init__(
        self,
        client: httpx.Client,
        page_size: int = 50,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the connector.

        Args:
            client: HTTP client whose ``base_url`` points at the ChEMBL API.
            page_size: Records requested per page.
            max_retries: Retries for transient failures, per page.
            backoff_seconds: Initial retry delay, doubled after each attempt.
            sleep: Sleep function (injectable for tests).
        """
        self._client = client
        self._page_size = page_size
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._sleep = sleep

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Fetch activities for ``spec.chembl_target``, paginating as needed.

        Args:
            spec: A ChEMBL source spec.

        Yields:
            Raw records across every page.

        Raises:
            IngestionError: If the spec has no target, or on request failure.
        """
        if spec.source is not SourceType.CHEMBL:
            raise IngestionError(f"ChemblConnector cannot fetch {spec.source.value!r}")
        if not spec.chembl_target:
            raise IngestionError("chembl source requires chembl_target")
        path: str | None = (
            f"/activity.json?target_chembl_id={spec.chembl_target}&limit={self._page_size}&offset=0"
        )
        pages_fetched = 0
        while path is not None:
            page = self._get_page(path)
            for activity in page.activities:
                yield activity.to_raw_record()
            pages_fetched += 1
            path = _normalize_next_path(page.page_meta.next)
        logger.info(
            "chembl fetch complete",
            extra={"target": spec.chembl_target, "pages": pages_fetched},
        )

    def _get_page(self, path: str) -> _ActivityResponse:
        """GET one page, with retries on transient errors."""
        delay = self._backoff
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(path)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise IngestionError(f"ChEMBL unreachable: {exc}") from exc
                logger.warning("chembl transport error, retrying", extra={"error": str(exc)})
                self._sleep(delay)
                delay *= 2
                continue
            if response.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                logger.warning("chembl busy, retrying", extra={"status_code": response.status_code})
                self._sleep(delay)
                delay *= 2
                continue
            if response.is_error:
                raise IngestionError(
                    f"ChEMBL request failed ({response.status_code}): {response.text[:200]}"
                )
            try:
                return _ActivityResponse.model_validate_json(response.content)
            except ValidationError as exc:
                raise IngestionError(f"unexpected ChEMBL response shape: {exc}") from exc
        raise IngestionError("unreachable retry state")  # pragma: no cover


def _normalize_next_path(next_path: str | None) -> str | None:
    """Strip ChEMBL's absolute ``/chembl/api/data`` prefix from a ``next`` link.

    ChEMBL's pagination ``next`` field is an absolute path from the domain
    root; our client's ``base_url`` already includes ``/chembl/api/data``, so
    passing the raw value would double that segment.

    Args:
        next_path: The raw ``page_meta.next`` value.

    Returns:
        A path relative to the client's base URL, or ``None``.
    """
    if next_path is None:
        return None
    return next_path.removeprefix("/chembl/api/data")


def build_chembl_client(
    base_url: str, timeout_seconds: float, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Create an HTTP client configured for the ChEMBL REST API.

    Args:
        base_url: ChEMBL API base URL.
        timeout_seconds: Request timeout.
        transport: Optional transport override (tests, fixture recording).

    Returns:
        A configured ``httpx.Client``.
    """
    return httpx.Client(
        base_url=base_url,
        timeout=timeout_seconds,
        headers={"User-Agent": "dndlabs/0.1 (data-infrastructure platform)"},
        transport=transport,
    )
