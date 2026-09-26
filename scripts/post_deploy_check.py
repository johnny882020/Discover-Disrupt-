r"""Credential-free check of a freshly deployed D&D Labs API.

Waits out a free-tier cold start, then verifies:

- liveness (``/health``) and readiness (``/api/v1/health/ready``, which fails
  unless the database is at the deployed code's newest migration);
- with ``--expected-spec``, that the deployed routes are exactly the ones the
  deployed commit defines (a stale or partial deploy shows up here);
- that every protected route rejects an anonymous request with ``401``.

It sends no credentials and creates nothing, so it is safe to run against
production after every deploy. Exits non-zero on the first failure.

Usage:
    python scripts/post_deploy_check.py https://dndlabs-api.onrender.com \\
        --expected-spec expected-openapi.json
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
ADMIN_PREFIX = "/api/v1/admin/"


class DeployCheckError(Exception):
    """Raised when a check fails."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise DeployCheckError(message)


def operations(spec: dict[str, Any]) -> set[str]:
    """Return every operation in an OpenAPI document as ``"METHOD path"``.

    Args:
        spec: The OpenAPI document.

    Returns:
        The operations.
    """
    return {
        f"{method.upper()} {path}"
        for path, item in spec["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }


def protected_operations(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """Return the operations that must reject anonymous requests.

    Those declaring a security requirement (API key or session), plus the
    operator routes under ``/api/v1/admin/`` (``X-Admin-Secret``).

    Args:
        spec: The OpenAPI document.

    Returns:
        ``(method, path)`` pairs, sorted.
    """
    return sorted(
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS and (operation.get("security") or path.startswith(ADMIN_PREFIX))
    )


def wait_until_awake(client: httpx.Client, deadline_seconds: float) -> None:
    """Poll ``/health`` until it answers; Render's free tier cold-starts in 50s+.

    Args:
        client: Client bound to the API's base URL.
        deadline_seconds: How long to keep trying.

    Raises:
        DeployCheckError: If liveness does not report ok in time.
    """
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            health = client.get("/health").raise_for_status().json()
            _check(health == {"status": "ok"}, f"health: {health}")
            return
        except httpx.HTTPError as exc:
            if time.monotonic() >= deadline:
                raise DeployCheckError(f"no healthy response in {deadline_seconds}s") from exc
            time.sleep(5)


def run_checks(
    client: httpx.Client,
    expected_spec: dict[str, Any] | None = None,
    wake_timeout: float = 180.0,
) -> None:
    """Run every check against the API ``client`` points at.

    Args:
        client: Client bound to the API's base URL.
        expected_spec: The deployed commit's own OpenAPI document, if known.
        wake_timeout: Seconds to wait for a cold start.

    Raises:
        DeployCheckError: On the first failed check.
    """
    wait_until_awake(client, wake_timeout)
    typer.echo("  ok  liveness")

    ready = client.get("/api/v1/health/ready")
    _check(ready.status_code == 200, f"readiness: {ready.status_code} {ready.text}")
    typer.echo("  ok  readiness (database reachable and at the newest migration)")

    spec: dict[str, Any] = client.get("/openapi.json").raise_for_status().json()
    if expected_spec is not None:
        served, expected = operations(spec), operations(expected_spec)
        _check(
            served == expected,
            f"route mismatch: missing {sorted(expected - served)}, "
            f"unexpected {sorted(served - expected)}",
        )
        typer.echo(f"  ok  routes match the deployed commit ({len(served)} operations)")

    protected = protected_operations(spec)
    _check(bool(protected), "no protected operations found in the OpenAPI document")
    for method, path in protected:
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        status = client.request(method, url).status_code
        _check(status == 401, f"{method} {path} without credentials returned {status}, not 401")
    typer.echo(f"  ok  {len(protected)} protected operations reject anonymous requests")


def main(
    base_url: Annotated[str, typer.Argument(help="API base URL.")],
    expected_spec: Annotated[
        Path | None,
        typer.Option(help="OpenAPI JSON of the deployed commit, to compare routes against."),
    ] = None,
    wake_timeout: Annotated[float, typer.Option(help="Seconds to wait for a cold start.")] = 180.0,
) -> None:
    """Run the post-deploy checks and exit non-zero on the first failure."""
    typer.echo(f"Post-deploy check: {base_url}")
    expected = json.loads(expected_spec.read_text()) if expected_spec else None
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
            run_checks(client, expected, wake_timeout)
    except (DeployCheckError, httpx.HTTPError) as exc:
        typer.echo(f"  FAIL {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("All post-deploy checks passed.")


if __name__ == "__main__":
    typer.run(main)
