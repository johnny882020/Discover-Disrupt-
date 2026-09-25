"""NVIDIA BioNeMo NIM (GenMol) enrichment client.

GenMol is a property-guided molecule generator: given a seed SMILES, it
returns scored candidate analogs. There is no pure "embedding for an
existing molecule" endpoint in NVIDIA's published BioNeMo blueprints (see
docs/nvidia-nim.md), so enrichment here means "generate scored candidates
from each accepted record's structure", not annotate it in place.

The exact hosted (build.nvidia.com) base URL is unverified from this build
environment (no live network to NVIDIA's domains) — the real, source-verified
piece is the request/response JSON shape below, learned from NVIDIA's own
``generative-virtual-screening`` BioNeMo blueprint notebook. Everything
HTTP-shape-specific lives in ``_to_request_body``/``_from_response_body`` so
a hostname/path correction is a one-place change.
"""

from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ValidationError

from dndlabs.core.exceptions import EnrichmentError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import EnrichmentRequest, EnrichmentResult, GeneratedCandidate

logger = get_logger(__name__)


class _GenMolMolecule(BaseModel):
    """One generated molecule as returned by GenMol."""

    smiles: str
    score: float


class _GenMolResponse(BaseModel):
    """GenMol ``/generate`` response body."""

    molecules: list[_GenMolMolecule]


def _to_request_body(seed_smiles: str, num_candidates: int, scoring: str) -> dict[str, object]:
    """Build the GenMol request body for one seed molecule.

    Args:
        seed_smiles: The record's canonical SMILES, used as the generation seed.
        num_candidates: How many candidates to request.
        scoring: The oracle GenMol optimizes for (e.g. ``"QED"``).

    Returns:
        The JSON body, matching NVIDIA's documented GenMol contract exactly.
    """
    return {
        "smiles": seed_smiles,
        "num_molecules": num_candidates,
        "temperature": 1,
        "noise": 0.2,
        "step_size": 4,
        "scoring": scoring,
    }


def _from_response_body(body: bytes, scoring: str) -> list[GeneratedCandidate]:
    """Parse a GenMol response body into candidates.

    Args:
        body: Raw JSON response bytes.
        scoring: The scoring method that was requested (recorded on each candidate).

    Returns:
        The generated candidates.

    Raises:
        EnrichmentError: If the response does not match the expected shape.
    """
    try:
        parsed = _GenMolResponse.model_validate_json(body)
    except ValidationError as exc:
        raise EnrichmentError(f"unexpected GenMol response shape: {exc}") from exc
    return [
        GeneratedCandidate(smiles=m.smiles, score=m.score, scoring_method=scoring)
        for m in parsed.molecules
    ]


class HttpGenMolClient:
    """Calls a hosted NVIDIA BioNeMo GenMol NIM for property-guided generation."""

    model_id = "genmol"

    def __init__(
        self,
        client: httpx.Client,
        num_candidates: int = 5,
        scoring: str = "QED",
    ) -> None:
        """Create the client.

        Args:
            client: HTTP client configured with the NIM base URL and
                ``Authorization: Bearer <key>`` header already set.
            num_candidates: Candidates requested per seed molecule.
            scoring: The oracle GenMol optimizes for.
        """
        self._client = client
        self._num_candidates = num_candidates
        self._scoring = scoring

    def is_enabled(self) -> bool:
        """Whether this client can make real calls.

        Returns:
            Always True — this is the "real" client, selected only when a
            key is configured (see :mod:`dndlabs.enrichment.service`).
        """
        return True

    async def enrich_batch(self, requests: Sequence[EnrichmentRequest]) -> list[EnrichmentResult]:
        """Enrich a batch of records by calling GenMol once per record.

        Args:
            requests: Records to enrich.

        Returns:
            One result per request, in order. A failure for one record never
            raises; it is reported as ``status="failed"``.
        """
        results: list[EnrichmentResult] = []
        for request in requests:
            results.append(self._enrich_one(request))
        return results

    def _enrich_one(self, request: EnrichmentRequest) -> EnrichmentResult:
        """Call GenMol for a single record, catching all failure modes."""
        body = _to_request_body(request.smiles, self._num_candidates, self._scoring)
        try:
            response = self._client.post("/generate", json=body)
            response.raise_for_status()
            candidates = _from_response_body(response.content, self._scoring)
        except (httpx.HTTPError, EnrichmentError) as exc:
            logger.warning(
                "genmol enrichment failed",
                extra={"record_id": str(request.record_id), "error": str(exc)},
            )
            return EnrichmentResult(record_id=request.record_id, status="failed", error=str(exc))
        return EnrichmentResult(
            record_id=request.record_id,
            status="enriched",
            model_id=self.model_id,
            candidates=candidates,
        )


def build_nim_client(base_url: str, api_key: str, timeout_seconds: float) -> httpx.Client:
    """Create an HTTP client configured for the hosted NVIDIA BioNeMo NIM.

    Args:
        base_url: NIM base URL (``settings.nvidia_nim_base_url``).
        api_key: NVIDIA API key.
        timeout_seconds: Request timeout.

    Returns:
        A configured ``httpx.Client``.
    """
    return httpx.Client(
        base_url=base_url,
        timeout=timeout_seconds,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "dndlabs/0.1 (data-infrastructure platform)",
        },
    )
