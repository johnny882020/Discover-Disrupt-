"""Generate a synthetic lab-instrument / ELN CSV export with injected defects.

Usage:
    python scripts/generate_synthetic_lab_export.py --rows 200 --out lab_export.csv

Roughly ``--defect-rate`` of rows get one defect: invalid SMILES, missing
structure, unknown unit, non-numeric value, missing unit, negative value, or a
re-plated duplicate of an earlier compound written with a different SMILES.
"""

import csv
import random
from pathlib import Path
from typing import Annotated

import typer

from dndlabs.core.logging import configure_logging, get_logger

logger = get_logger("generate_synthetic_lab_export")

COMPOUNDS: list[tuple[str, str]] = [
    ("Aspirin", "CC(=O)OC1=CC=CC=C1C(=O)O"),
    ("Ibuprofen", "CC(C)CC1=CC=C(C=C1)C(C)C(=O)O"),
    ("Caffeine", "CN1C=NC2=C1C(=O)N(C(=O)N2C)C"),
    ("Acetaminophen", "CC(=O)NC1=CC=C(C=C1)O"),
    ("Metformin", "CN(C)C(=N)N=C(N)N"),
    ("Diclofenac", "C1=CC=C(C(=C1)CC(=O)O)NC2=C(C=CC=C2Cl)Cl"),
    ("Ketoprofen", "CC(C1=CC(=CC=C1)C(=O)C2=CC=CC=C2)C(=O)O"),
    ("Nifedipine", "CC1=C(C(C(=C(N1)C)C(=O)OC)C2=CC=CC=C2[N+](=O)[O-])C(=O)OC"),
]
UNITS = ["nM", "uM", "µM", "mM", "pM"]
TARGETS = ["COX-1", "COX-2", "EGFR", "ADORA2A", "HERG"]
HEADER = [
    "compound_id", "name", "smiles", "activity_type",
    "activity_value", "activity_unit", "target", "plate",
]  # fmt: skip
DEFECTS = ["bad_smiles", "no_structure", "bad_unit", "bad_value", "no_unit", "negative"]


def _row(index: int, rng: random.Random) -> dict[str, str]:
    """Build one clean row."""
    name, smiles = COMPOUNDS[index % len(COMPOUNDS)]
    return {
        "compound_id": f"LAB-{index + 1:05d}",
        "name": f"{name} #{index // len(COMPOUNDS) + 1}",
        "smiles": smiles,
        "activity_type": rng.choice(["IC50", "Ki", "EC50"]),
        "activity_value": f"{rng.uniform(0.01, 5000):.3f}",
        "activity_unit": rng.choice(UNITS),
        "target": rng.choice(TARGETS),
        "plate": f"P{index // 96 + 1}",
    }


def _inject(row: dict[str, str], defect: str) -> dict[str, str]:
    """Apply one defect to a row."""
    changes = {
        "bad_smiles": {"smiles": row["smiles"] + "(("},
        "no_structure": {"smiles": ""},
        "bad_unit": {"activity_unit": "furlongs"},
        "bad_value": {"activity_value": "n/a"},
        "no_unit": {"activity_unit": ""},
        "negative": {"activity_value": "-1"},
    }[defect]
    return {**row, **changes}


def main(
    rows: Annotated[int, typer.Option(min=1)] = 100,
    out: Annotated[Path, typer.Option()] = Path("lab_export.csv"),
    defect_rate: Annotated[float, typer.Option(min=0.0, max=1.0)] = 0.2,
    seed: int = 7,
) -> None:
    """Write the synthetic export.

    Unique structures are limited to the built-in compound list, so rows beyond
    that list are duplicates by design (exercising duplicate detection).
    """
    configure_logging("INFO", json_output=False)
    rng = random.Random(seed)
    counts: dict[str, int] = {}
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        for index in range(rows):
            row = _row(index, rng)
            if rng.random() < defect_rate:
                defect = rng.choice(DEFECTS)
                counts[defect] = counts.get(defect, 0) + 1
                row = _inject(row, defect)
            writer.writerow(row)
    logger.info("wrote %d rows to %s; defects: %s", rows, out, counts)


if __name__ == "__main__":
    typer.run(main)
