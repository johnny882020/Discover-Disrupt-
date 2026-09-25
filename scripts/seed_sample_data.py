"""Bootstrap a demo organization and seed it with the sample datasets.

Uses the bundled fixtures (no live network needed for CSV/JSON; PubChem
and ChEMBL use recorded responses unless --live is passed).

Usage:
    python scripts/seed_sample_data.py
"""

from pathlib import Path
from typing import Annotated

import httpx
import typer

from dndlabs.core.config import get_settings
from dndlabs.core.logging import configure_logging, get_logger
from dndlabs.core.schemas import Organization, SourceSpec, SourceType
from dndlabs.pipeline.factory import build_container

logger = get_logger("seed_sample_data")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _recorded_pubchem() -> httpx.MockTransport:
    body = (FIXTURES / "pubchem" / "properties_3.json").read_bytes()
    return httpx.MockTransport(lambda _r: httpx.Response(200, content=body))


def main(live: Annotated[bool, typer.Option(help="Call PubChem for real.")] = False) -> None:
    """Seed a demo org with datasets from every source."""
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    container = build_container(settings, pubchem_transport=None if live else _recorded_pubchem())
    try:
        org = container.repositories.organizations.create(Organization(name="Demo Org"))
        key = container.auth.issue_key(org)
        logger.info("created demo org %s with key %s", org.id, key.raw_key)
        specs = [
            SourceSpec(
                source=SourceType.PUBCHEM,
                identifiers=["2244", "3672", "2519"],
                dataset_name="pubchem-sample",
            ),
            SourceSpec(
                source=SourceType.CSV,
                csv_path=str(FIXTURES / "lab_export_malformed.csv"),
                dataset_name="lab-export",
            ),
            SourceSpec(
                source=SourceType.JSON,
                json_path=str(FIXTURES / "data_lake_upload.json"),
                dataset_name="data-lake",
            ),
        ]
        for spec in specs:
            import asyncio

            run = container.service.submit(org.id, spec)
            finished = asyncio.run(container.service.execute(org.id, run.id))
            logger.info(
                "seeded %s: run=%s status=%s", spec.dataset_name, finished.id, finished.status
            )
    finally:
        container.close()


if __name__ == "__main__":
    typer.run(main)
