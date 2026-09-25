"""Seed the configured database with the bundled sample datasets.

Runs the pipeline over the recorded PubChem sample (no network needed), the
malformed lab CSV, and the data-lake JSON upload in ``tests/fixtures``.

Usage:
    python scripts/seed_sample_data.py            # uses DNDLABS_* settings
    python scripts/seed_sample_data.py --live     # fetch the PubChem sample live
"""

import json
from pathlib import Path
from typing import Annotated

import httpx
import typer

from dndlabs.core.config import get_settings
from dndlabs.core.logging import configure_logging, get_logger
from dndlabs.core.schemas import SourceSpec, SourceType
from dndlabs.pipeline.factory import build_container

logger = get_logger("seed_sample_data")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _recorded_transport() -> httpx.MockTransport:
    """Serve the recorded PubChem response for CID requests."""
    body = (FIXTURES / "pubchem_properties_12.json").read_bytes()
    return httpx.MockTransport(lambda _request: httpx.Response(200, content=body))


def main(live: Annotated[bool, typer.Option(help="Call PubChem for real.")] = False) -> None:
    """Run the sample pipelines and log the resulting dataset ids."""
    settings = get_settings()
    configure_logging(settings.log_level, json_output=False)
    cids = [
        str(p["CID"])
        for p in json.loads((FIXTURES / "pubchem_properties_12.json").read_text())["PropertyTable"][
            "Properties"
        ]
    ]
    specs = [
        SourceSpec(source=SourceType.PUBCHEM, identifiers=cids, dataset_name="pubchem-sample"),
        SourceSpec(
            source=SourceType.CSV,
            path=str(FIXTURES / "lab_export_malformed.csv"),
            dataset_name="lab-export-malformed",
        ),
        SourceSpec(
            source=SourceType.JSON,
            path=str(FIXTURES / "data_lake_upload.json"),
            dataset_name="data-lake-upload",
        ),
    ]
    container = build_container(settings, None if live else _recorded_transport())
    try:
        for spec in specs:
            result = container.service.run(spec)
            logger.info(
                "seeded %s: dataset=%s accepted=%d/%d",
                result.dataset.name,
                result.dataset.id,
                result.report.accepted_records,
                result.report.total_records,
            )
    finally:
        container.close()


if __name__ == "__main__":
    typer.run(main)
