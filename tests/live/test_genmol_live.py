"""Opt-in check against the live NVIDIA BioNeMo GenMol NIM.

Requires a real DNDLABS_NVIDIA_NIM_API_KEY and confirms/corrects the
hosted base URL guess documented in docs/nvidia-nim.md.
"""

import os

import pytest

from dndlabs.core.schemas import EnrichmentRequest
from dndlabs.enrichment.client import HttpGenMolClient, build_nim_client

API_KEY = os.environ.get("DNDLABS_NVIDIA_NIM_API_KEY")
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("DNDLABS_LIVE_TESTS") != "1" or not API_KEY,
        reason="set DNDLABS_LIVE_TESTS=1 and DNDLABS_NVIDIA_NIM_API_KEY",
    ),
]

BASE = "https://health.api.nvidia.com/v1/biology/nvidia/genmol"


async def test_live_genmol_generates_candidates() -> None:
    assert API_KEY is not None
    with build_nim_client(BASE, API_KEY, 60) as client:
        client_wrapper = HttpGenMolClient(client, num_candidates=2, scoring="QED")
        [result] = await client_wrapper.enrich_batch(
            [
                EnrichmentRequest(
                    record_id=__import__("uuid").uuid4(), smiles="CC(=O)Oc1ccccc1C(=O)O"
                )
            ]
        )
    assert result.status == "enriched", result.error
