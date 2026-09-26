r"""End-to-end smoke test against a running D&D Labs Platform deployment.

Runs as a dedicated smoke-test organization, using that organization's API
key, never the operator's admin secret. A second organization's key checks
tenant isolation. Both organizations must have "smoke" in their name, so a
customer's key can never be used by mistake.

Waits out a free-tier cold start, then checks liveness and readiness; the
key's identity; user accounts (invite a member, accept, sign out, sign in,
remove); a file upload with the suggested and a saved column mapping, run
to completion; the quality report, enrichment status and export; that the
second organization cannot see any of it; and the API docs. Everything it
creates is deleted at the end, pass or fail. Exits non-zero on the first
failure.

Usage:
    DNDLABS_SMOKE_API_KEY=<key> DNDLABS_SMOKE_ISOLATION_API_KEY=<key> \\
        python scripts/smoke_test.py https://dndlabs-api.onrender.com
"""

import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx
import typer

TERMINAL = {"succeeded", "failed"}

UPLOAD_CSV = (
    "Compound ID,Structure,Activity Value,Unit\n"
    "SMOKE-1,CC(=O)Oc1ccccc1C(=O)O,0.12,uM\n"
    "SMOKE-2,Cn1cnc2c1c(=O)n(C)c(=O)n2C,45,nM\n"
)
#: Headers by alias, and the unlabelled structure column by its contents.
EXPECTED_MAPPING = {
    "Compound ID": "source_record_id",
    "Structure": "smiles",
    "Activity Value": "activity_value",
    "Unit": "activity_unit",
}
TEMPLATE_NAME = "Smoke test mapping"


class SmokeCheckError(Exception):
    """Raised when a check fails."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeCheckError(message)


@dataclass
class Created:
    """What the smoke test created, so it can be removed afterwards."""

    user_ids: list[str] = field(default_factory=list)
    template_ids: list[str] = field(default_factory=list)


def _wait_until_awake(client: httpx.Client, deadline_seconds: float) -> None:
    """Poll ``/health`` until it answers; Render's free tier cold-starts in 50s+."""
    deadline = time.monotonic() + deadline_seconds
    while True:
        try:
            health = client.get("/health").raise_for_status().json()
            _check(health == {"status": "ok"}, f"health: {health}")
            return
        except httpx.HTTPError as exc:
            if time.monotonic() >= deadline:
                raise SmokeCheckError(f"no healthy response in {deadline_seconds}s") from exc
            time.sleep(5)


def _wait_for_run(
    client: httpx.Client, headers: dict[str, str], run_id: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        run: dict[str, Any] = (
            client.get(f"/api/v1/pipelines/runs/{run_id}", headers=headers)
            .raise_for_status()
            .json()
        )
        if run["status"] in TERMINAL:
            return run
        _check(time.monotonic() < deadline, f"run {run_id} still {run['status']} after {timeout}s")
        time.sleep(1)


def _smoke_identity(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    """Return the key's identity, refusing any organization not named for smoke tests."""
    whoami: dict[str, Any] = (
        client.get("/api/v1/auth/whoami", headers=headers).raise_for_status().json()
    )
    _check(
        "smoke" in whoami["org_name"].lower(),
        f"refusing to run as organization {whoami['org_name']!r}: its name must "
        "contain 'smoke' (use a dedicated smoke-test organization's key)",
    )
    _check(
        (whoami["principal"], whoami["role"]) == ("api_key", "admin"),
        f"expected an organization API key, got {whoami['principal']}/{whoami['role']}",
    )
    return whoami


def _check_user_accounts(
    client: httpx.Client, headers: dict[str, str], org_id: str, created: Created
) -> None:
    """Invite a member, redeem, sign out and in, then remove them."""
    email = f"smoke-{uuid.uuid4().hex[:12]}@example.com"
    password = secrets.token_urlsafe(18)
    invitation = (
        client.post(
            "/api/v1/auth/invitations", json={"email": email, "role": "member"}, headers=headers
        )
        .raise_for_status()
        .json()
    )
    session = (
        client.post(
            "/api/v1/auth/invitations/accept",
            json={"token": invitation["token"], "password": password},
        )
        .raise_for_status()
        .json()
    )
    user_id = session["user"]["id"]
    created.user_ids.append(user_id)

    bearer = {"Authorization": f"Bearer {session['token']}"}
    client.post("/api/v1/auth/logout", headers=bearer).raise_for_status()
    revoked = client.get("/api/v1/auth/whoami", headers=bearer)
    _check(revoked.status_code == 401, f"signed-out token still works: {revoked.status_code}")

    login = (
        client.post("/api/v1/auth/login", json={"email": email, "password": password})
        .raise_for_status()
        .json()
    )
    bearer = {"Authorization": f"Bearer {login['token']}"}
    whoami = client.get("/api/v1/auth/whoami", headers=bearer).raise_for_status().json()
    _check(
        (whoami["org_id"], whoami["principal"], whoami["role"]) == (org_id, "user", "member"),
        f"member whoami: {whoami}",
    )

    client.delete(f"/api/v1/auth/members/{user_id}", headers=headers).raise_for_status()
    created.user_ids.remove(user_id)
    removed = client.get("/api/v1/auth/whoami", headers=bearer)
    _check(removed.status_code == 401, f"removed member still signed in: {removed.status_code}")
    typer.echo("  ok  user accounts: invite, accept, sign out, sign in, remove")


def _check_upload_run(
    client: httpx.Client, headers: dict[str, str], timeout: float, created: Created
) -> tuple[str, str]:
    """Upload a CSV, save its mapping as a template, and run it; return (upload, dataset) ids."""
    preview = (
        client.post(
            "/api/v1/uploads",
            files={"file": ("smoke.csv", UPLOAD_CSV.encode(), "text/csv")},
            headers=headers,
        )
        .raise_for_status()
        .json()
    )
    upload_id = preview["upload"]["id"]
    mapping = preview["suggested_mapping"]
    _check(preview["row_count"] == 2, f"upload preview rows: {preview['row_count']}")
    _check(mapping == EXPECTED_MAPPING, f"suggested mapping: {mapping}")

    template = (
        client.post(
            "/api/v1/mapping-templates",
            json={"name": TEMPLATE_NAME, "mapping": mapping},
            headers=headers,
        )
        .raise_for_status()
        .json()
    )
    created.template_ids.append(template["id"])
    again = (
        client.get(f"/api/v1/uploads/{upload_id}/preview", headers=headers)
        .raise_for_status()
        .json()
    )
    _check(
        (again["template"] or {}).get("id") == template["id"],
        f"saved mapping not suggested: {again['template']}",
    )

    response = client.post(
        "/api/v1/pipelines/run",
        json={
            "source": "upload",
            "upload_id": upload_id,
            "column_mapping": mapping,
            "dataset_name": "smoke-upload",
        },
        headers=headers,
    )
    _check(response.status_code == 202, f"upload run: {response.status_code} {response.text}")
    run = _wait_for_run(client, headers, response.json()["id"], timeout)
    _check(run["status"] == "succeeded", f"upload run failed: {run['error']}")
    typer.echo("  ok  upload: preview, suggested and saved mapping, run")
    return upload_id, run["dataset_id"]


def _check_dataset(client: httpx.Client, headers: dict[str, str], dataset_id: str) -> None:
    """Check the dataset's quality report, enrichment status and export."""
    report = (
        client.get(f"/api/v1/datasets/{dataset_id}/quality-report", headers=headers)
        .raise_for_status()
        .json()
    )
    counts = (report["accepted_records"], report["total_records"])
    _check(counts == (2, 2), f"quality report accepted/total: {counts}")
    typer.echo("  ok  quality report: 2/2 accepted")

    enrichment = (
        client.get(f"/api/v1/datasets/{dataset_id}/enrichment", headers=headers)
        .raise_for_status()
        .json()
    )
    typer.echo(f"  ok  enrichment status: enabled={enrichment['enrichment_enabled']}")

    export = client.get(f"/api/v1/datasets/{dataset_id}/export?format=jsonl", headers=headers)
    _check(export.status_code == 200, f"export: {export.status_code}")
    activity = {
        record["source_record_id"]: record["activity_value_nm"]
        for record in map(json.loads, export.text.splitlines())
    }
    _check(activity == {"SMOKE-1": 120.0, "SMOKE-2": 45.0}, f"exported activity (nM): {activity}")
    typer.echo("  ok  export: identifiers kept, activity normalized to nM")


def _check_isolation(
    client: httpx.Client, other_headers: dict[str, str], upload_id: str, dataset_id: str
) -> None:
    """The second organization must not see the first one's dataset or upload."""
    for path in (f"/api/v1/datasets/{dataset_id}", f"/api/v1/uploads/{upload_id}/preview"):
        status = client.get(path, headers=other_headers).status_code
        _check(status == 404, f"org isolation: {path} returned {status} to another org")
    listed = client.get("/api/v1/datasets", headers=other_headers).raise_for_status().json()
    _check(
        all(d["id"] != dataset_id for d in listed),
        "org isolation: dataset listed for another org",
    )
    typer.echo("  ok  org isolation")


def _clean_up(client: httpx.Client, headers: dict[str, str], created: Created) -> None:
    """Delete everything the smoke test created in its organization."""
    for user_id in created.user_ids:
        response = client.delete(f"/api/v1/auth/members/{user_id}", headers=headers)
        _check(response.status_code in (204, 404), f"cleanup: member {response.status_code}")
    for template_id in created.template_ids:
        response = client.delete(f"/api/v1/mapping-templates/{template_id}", headers=headers)
        _check(response.status_code in (204, 404), f"cleanup: template {response.status_code}")
    client.delete("/api/v1/orgs/me/data", headers=headers).raise_for_status()
    remaining = client.get("/api/v1/datasets", headers=headers).raise_for_status().json()
    _check(remaining == [], f"cleanup: {len(remaining)} datasets remain")


def run_smoke(
    client: httpx.Client,
    api_key: str,
    isolation_api_key: str,
    timeout: float = 60.0,
    wake_timeout: float = 180.0,
) -> None:
    """Run every check against the API ``client`` points at.

    Args:
        client: Client bound to the API's base URL.
        api_key: API key of the smoke-test organization.
        isolation_api_key: API key of a second smoke-test organization.
        timeout: Seconds to wait for a pipeline run.
        wake_timeout: Seconds to wait for a cold start.

    Raises:
        SmokeCheckError: On the first failed check, or if cleanup fails.
    """
    _wait_until_awake(client, wake_timeout)
    typer.echo("  ok  liveness")
    ready = client.get("/api/v1/health/ready")
    _check(ready.status_code == 200, f"readiness: {ready.status_code} {ready.text}")
    typer.echo("  ok  readiness (database reachable and at the newest migration)")

    headers = {"X-API-Key": api_key}
    other_headers = {"X-API-Key": isolation_api_key}
    org = _smoke_identity(client, headers)
    other = _smoke_identity(client, other_headers)
    _check(org["org_id"] != other["org_id"], "the two keys belong to the same organization")
    typer.echo(f"  ok  identity: {org['org_name']!r} and {other['org_name']!r}")

    created = Created()
    try:
        _check_user_accounts(client, headers, org["org_id"], created)
        upload_id, dataset_id = _check_upload_run(client, headers, timeout, created)
        _check_dataset(client, headers, dataset_id)
        _check_isolation(client, other_headers, upload_id, dataset_id)
        docs = client.get("/docs")
        _check(docs.status_code == 200, f"/docs: {docs.status_code}")
        typer.echo("  ok  /docs")
    except BaseException:
        # Clean up without letting a cleanup error hide the original failure.
        try:
            _clean_up(client, headers, created)
        except (SmokeCheckError, httpx.HTTPError) as cleanup_error:
            typer.echo(f"  FAIL cleanup after the failure below: {cleanup_error}", err=True)
        raise
    _clean_up(client, headers, created)
    typer.echo("  ok  cleanup: test data removed")


def main(
    base_url: Annotated[str, typer.Argument(help="API base URL.")],
    api_key: Annotated[
        str, typer.Option(envvar="DNDLABS_SMOKE_API_KEY", help="Smoke-test organization's key.")
    ],
    isolation_api_key: Annotated[
        str,
        typer.Option(
            envvar="DNDLABS_SMOKE_ISOLATION_API_KEY",
            help="A second smoke-test organization's key, for the isolation check.",
        ),
    ],
    timeout: Annotated[float, typer.Option(help="Seconds to wait per run.")] = 60.0,
    wake_timeout: Annotated[float, typer.Option(help="Seconds to wait for a cold start.")] = 180.0,
) -> None:
    """Run the smoke test and exit non-zero on the first failure."""
    typer.echo(f"Smoke test: {base_url}")
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0) as client:
            run_smoke(client, api_key, isolation_api_key, timeout, wake_timeout)
    except (SmokeCheckError, httpx.HTTPError) as exc:
        typer.echo(f"  FAIL {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("All smoke checks passed.")


if __name__ == "__main__":
    typer.run(main)
