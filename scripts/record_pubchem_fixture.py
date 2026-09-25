"""Re-record ``tests/fixtures/pubchem_properties_12.json`` from the live PubChem API.

Usage:
    python scripts/record_pubchem_fixture.py
"""

import json
from pathlib import Path

from dndlabs.core.config import get_settings
from dndlabs.core.logging import configure_logging, get_logger
from dndlabs.ingestion.pubchem import PROPERTIES, build_pubchem_client

logger = get_logger("record_pubchem_fixture")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
CIDS = [2244, 3672, 5090, 2519, 1983, 4091, 2662, 3386, 156391, 3033, 4485, 3825]


def main() -> None:
    """Fetch the sample CIDs and overwrite the fixture files."""
    settings = get_settings()
    configure_logging("INFO", json_output=False)
    props = ",".join(PROPERTIES)
    with build_pubchem_client(settings.pubchem_base_url, settings.pubchem_timeout_seconds) as http:
        cid_response = http.get(f"/compound/cid/{','.join(map(str, CIDS))}/property/{props}/JSON")
        cid_response.raise_for_status()
        name_response = http.get(f"/compound/name/aspirin/property/{props}/JSON")
        name_response.raise_for_status()
    for filename, response in [
        ("pubchem_properties_12.json", cid_response),
        ("pubchem_name_aspirin.json", name_response),
    ]:
        path = FIXTURES / filename
        path.write_text(json.dumps(response.json(), indent=2) + "\n", encoding="utf-8")
        logger.info("wrote %s", path)


if __name__ == "__main__":
    main()
