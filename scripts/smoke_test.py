"""End-to-end smoke test against a running D&D Labs API.

Checks the root and health endpoints, runs the bundled sample CSV and JSON
through the pipeline, and verifies each dataset, quality report and export.
It can also run a live PubChem request.

Usage:
    python scripts/smoke_test.py https://<service>.onrender.com
    python scripts/smoke_test.py http://localhost:8000 --pubchem
    python scripts/smoke_test.py http://localhost:8000 --samples-dir tests/fixtures
"""

import time
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import typer

TERMINAL = {"succeeded", "failed"}


@dataclass(frozen=True)
class Case:
    """One pipeline run and the quality-report counts it must produce."""

    label: str
    spec: dict[str, Any]
    expected: dict[str, int] | None  # None: only require success


class SmokeCheckError(Exception):
    """Raised when a check fails."""


def _check(condition: bool, message: str) -> None:
    """Fail the smoke test with ``message`` unless ``condition`` holds."""
    if not condition:
        raise SmokeCheckError(message)


def _wait_for_run(client: httpx.Client, run_id: str, timeout: float) -> dict[str, Any]:
    """Poll a run until it reaches a terminal status."""
    deadline = time.monotonic() + timeout
    while True:
        run: dict[str, Any] = client.get(f"/pipelines/runs/{run_id}").raise_for_status().json()
        if run["status"] in TERMINAL:
            return run
        _check(time.monotonic() < deadline, f"run {run_id} still {run['status']} after {timeout}s")
        time.sleep(1)


def _run_case(client: httpx.Client, case: Case, timeout: float) -> None:
    """Run one case and verify its dataset, report and export."""
    response = client.post("/pipelines/run", json=case.spec)
    _check(response.status_code == 202, f"{case.label}: POST returned {response.status_code}")
    run = _wait_for_run(client, response.json()["id"], timeout)
    _check(run["status"] == "succeeded", f"{case.label}: run failed: {run['error']}")

    dataset_id = run["dataset_id"]
    dataset = client.get(f"/datasets/{dataset_id}").raise_for_status().json()
    report = client.get(f"/datasets/{dataset_id}/quality-report").raise_for_status().json()
    export = client.get(f"/datasets/{dataset_id}/export").raise_for_status()

    _check(len(dataset["records"]) == report["accepted_records"], f"{case.label}: count mismatch")
    _check(
        len(export.text.strip().splitlines()) == report["accepted_records"] + 1,
        f"{case.label}: export row count mismatch",
    )
    if case.expected:
        actual = {key: report[key] for key in case.expected}
        _check(actual == case.expected, f"{case.label}: expected {case.expected}, got {actual}")
    typer.echo(
        f"  ok  {case.label}: {report['accepted_records']}/{report['total_records']} accepted, "
        f"pass rate {report['pass_rate']:.1%}"
    )


#: (label, method, path, JSON body, expected status) for error handling.
ERROR_CASES: list[tuple[str, str, str, dict[str, Any] | None, int]] = [
    ("unknown path", "GET", "/no-such-route", None, 404),
    ("unknown run", "GET", "/pipelines/runs/does-not-exist", None, 404),
    ("unknown dataset", "GET", "/datasets/does-not-exist", None, 404),
    ("unknown report", "GET", "/datasets/does-not-exist/quality-report", None, 404),
    ("bad export format", "GET", "/datasets/does-not-exist/export?format=xml", None, 422),
    ("missing identifiers", "POST", "/pipelines/run", {"source": "pubchem"}, 422),
    ("non-numeric CID", "POST", "/pipelines/run", {"source": "pubchem", "identifiers": ["x"]}, 422),
    ("unsupported source", "POST", "/pipelines/run", {"source": "chembl"}, 422),
]


def _check_errors(client: httpx.Client) -> None:
    """Verify that bad requests get clean 4xx responses, never 5xx."""
    for label, method, path, body, expected in ERROR_CASES:
        response = client.request(method, path, json=body)
        _check(
            response.status_code == expected,
            f"{label}: expected {expected}, got {response.status_code} {response.text[:200]}",
        )
        _check("detail" in response.json(), f"{label}: error body has no detail")
    typer.echo(f"  ok  error handling: {len(ERROR_CASES)} bad requests rejected cleanly")


def main(
    base_url: Annotated[str, typer.Argument(help="API base URL.")],
    samples_dir: Annotated[
        str, typer.Option(help="Sample-file directory as seen by the server.")
    ] = "/app/samples",
    pubchem: Annotated[bool, typer.Option(help="Also run a live PubChem request.")] = False,
    timeout: Annotated[float, typer.Option(help="Seconds to wait per run.")] = 120.0,
) -> None:
    """Run the smoke test and exit non-zero on the first failure."""
    cases = [
        Case(
            "csv lab export",
            {"source": "csv", "path": f"{samples_dir}/lab_export_malformed.csv"},
            {
                "total_records": 12,
                "accepted_records": 5,
                "rejected_records": 6,
                "duplicate_records": 1,
            },
        ),
        Case(
            "json upload",
            {"source": "json", "path": f"{samples_dir}/data_lake_upload.json"},
            {"total_records": 4, "accepted_records": 2, "rejected_records": 2},
        ),
    ]
    if pubchem:
        cases.append(
            Case(
                "pubchem cids",
                {"source": "pubchem", "identifiers": ["2244", "3672", "5090"]},
                {"total_records": 3, "accepted_records": 3},
            )
        )
        cases.append(
            Case(
                "pubchem names",
                {
                    "source": "pubchem",
                    "identifiers": ["aspirin", "caffeine", "not-a-real-compound-xyz"],
                    "identifier_type": "name",
                },
                {"total_records": 2, "accepted_records": 2},  # unknown name is skipped
            )
        )
    typer.echo(f"Smoke test: {base_url}")
    try:
        # Generous timeout: free hosting tiers cold-start on the first request.
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=90.0) as client:
            root = client.get("/").raise_for_status().json()
            _check(root.get("docs") == "/docs", "root: unexpected response")
            typer.echo(f"  ok  root: {root['name']} {root['version']}")
            health = client.get("/health").raise_for_status().json()
            _check(health == {"status": "ok"}, f"health: {health}")
            typer.echo("  ok  health")
            _check(client.get("/docs").status_code == 200, "docs: not served")
            typer.echo("  ok  /docs")
            _check_errors(client)
            for case in cases:
                _run_case(client, case, timeout)
    except (SmokeCheckError, httpx.HTTPError) as exc:
        typer.echo(f"  FAIL {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("All smoke checks passed.")


if __name__ == "__main__":
    typer.run(main)
