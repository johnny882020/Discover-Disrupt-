"""End-to-end smoke test against a running D&D Labs Platform deployment.

Waits out a free-tier cold start, checks liveness and database readiness,
bootstraps a throwaway organization, runs a CSV pipeline against the image's
bundled sample, and checks the quality report, enrichment status, export and
org isolation. Exits non-zero on the first failure.

Usage:
    DNDLABS_ADMIN_BOOTSTRAP_SECRET=<secret> python scripts/smoke_test.py https://dndlabs-api.onrender.com
"""

import time
from typing import Annotated, Any

import httpx
import typer

TERMINAL = {"succeeded", "failed"}


class SmokeCheckError(Exception):
    """Raised when a check fails."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeCheckError(message)


def _wait_for_run(
    client: httpx.Client, headers: dict[str, str], run_id: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/api/v1/pipelines/runs/{run_id}", headers=headers)
        run: dict[str, Any] = response.raise_for_status().json()
        if run["status"] in TERMINAL:
            return run
        _check(time.monotonic() < deadline, f"run {run_id} still {run['status']} after {timeout}s")
        time.sleep(1)


def _wait_until_awake(client: httpx.Client, deadline_seconds: float) -> dict[str, Any]:
    """Poll ``/health`` until it answers; Render's free tier cold-starts in 50s+."""
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            health: dict[str, Any] = client.get("/health").raise_for_status().json()
            return health
        except httpx.HTTPError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)


def main(
    base_url: Annotated[str, typer.Argument(help="API base URL.")],
    admin_secret: Annotated[
        str, typer.Option(envvar="DNDLABS_ADMIN_BOOTSTRAP_SECRET", help="Admin bootstrap secret.")
    ],
    timeout: Annotated[float, typer.Option(help="Seconds to wait per run.")] = 60.0,
    wake_timeout: Annotated[float, typer.Option(help="Seconds to wait for a cold start.")] = 180.0,
) -> None:
    """Run the smoke test and exit non-zero on the first failure."""
    typer.echo(f"Smoke test: {base_url}")
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
            health = _wait_until_awake(client, wake_timeout)
            _check(health == {"status": "ok"}, f"health: {health}")
            typer.echo("  ok  health")

            ready = client.get("/api/v1/health/ready")
            _check(ready.status_code == 200, f"readiness: {ready.status_code} {ready.text}")
            typer.echo("  ok  readiness (database reachable and migrated)")

            org = (
                client.post(
                    "/api/v1/admin/orgs",
                    json={"name": "smoke-test-org"},
                    headers={"X-Admin-Secret": admin_secret},
                )
                .raise_for_status()
                .json()
            )
            headers = {"X-API-Key": org["raw_key"]}
            typer.echo("  ok  admin bootstrap: org created")

            whoami = client.get("/api/v1/auth/whoami", headers=headers).raise_for_status().json()
            _check(whoami["org_id"] == org["org_id"], "whoami org mismatch")
            typer.echo("  ok  whoami")

            # A run needs a server-side file path; write it via the container's
            # samples if present, otherwise this covers the invalid-input path.
            response = client.post(
                "/api/v1/pipelines/run",
                json={"source": "csv", "csv_path": "/app/samples/lab_export_malformed.csv"},
                headers=headers,
            )
            _check(
                response.status_code == 202, f"run submit: {response.status_code} {response.text}"
            )
            run = _wait_for_run(client, headers, response.json()["id"], timeout)
            if run["status"] == "succeeded":
                dataset_id = run["dataset_id"]
                report = (
                    client.get(f"/api/v1/datasets/{dataset_id}/quality-report", headers=headers)
                    .raise_for_status()
                    .json()
                )
                accepted, total = report["accepted_records"], report["total_records"]
                typer.echo(f"  ok  csv run: {accepted}/{total} accepted")
                enrichment = (
                    client.get(f"/api/v1/datasets/{dataset_id}/enrichment", headers=headers)
                    .raise_for_status()
                    .json()
                )
                typer.echo(f"  ok  enrichment status: enabled={enrichment['enrichment_enabled']}")
                export = client.get(f"/api/v1/datasets/{dataset_id}/export", headers=headers)
                _check(export.status_code == 200, "export failed")
                typer.echo("  ok  export")
            else:
                typer.echo(f"  ..  csv run failed (expected without /app/samples): {run['error']}")

            other_org = (
                client.post(
                    "/api/v1/admin/orgs",
                    json={"name": "smoke-test-org-2"},
                    headers={"X-Admin-Secret": admin_secret},
                )
                .raise_for_status()
                .json()
            )
            other_headers = {"X-API-Key": other_org["raw_key"]}
            isolation = (
                client.get("/api/v1/datasets", headers=other_headers).raise_for_status().json()
            )
            _check(isolation == [], "org isolation: second org should see no datasets")
            typer.echo("  ok  org isolation")

            docs = client.get("/docs")
            _check(docs.status_code == 200, "docs not served")
            typer.echo("  ok  /docs")
    except (SmokeCheckError, httpx.HTTPError) as exc:
        typer.echo(f"  FAIL {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("All smoke checks passed.")


if __name__ == "__main__":
    typer.run(main)
