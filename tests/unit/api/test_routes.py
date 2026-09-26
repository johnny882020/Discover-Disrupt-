import dataclasses
import time
import uuid

from fastapi.testclient import TestClient

from dndlabs.api.app import create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.core.exceptions import StorageError
from dndlabs.core.schemas import ApiKeyCreated

ADMIN = {"X-Admin-Secret": "test-admin-secret"}


def _run_csv(client: TestClient, headers: dict[str, str]) -> dict:  # type: ignore[type-arg]
    response = client.post(
        "/api/v1/pipelines/run", json={"source": "csv", "csv_path": "x.csv"}, headers=headers
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    for _ in range(20):
        status = client.get(f"/api/v1/pipelines/runs/{run_id}", headers=headers).json()
        if status["status"] in ("succeeded", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_readiness_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_readiness_reports_503_when_storage_is_broken(services: ApiServices) -> None:
    class BrokenOrganizations:
        def ping(self) -> None:
            raise StorageError('relation "organizations" does not exist')

    broken_repos = dataclasses.replace(
        services.repositories,
        organizations=BrokenOrganizations(),  # type: ignore[arg-type]
    )
    broken_services = dataclasses.replace(services, repositories=broken_repos)
    with TestClient(create_app(broken_services)) as broken_client:
        response = broken_client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_root_serves_html_to_browsers(client: TestClient) -> None:
    response = client.get("/", headers={"Accept": "text/html"})
    assert response.headers["content-type"].startswith("text/html")
    assert "D&amp;D Labs" in response.text


def test_root_json_by_default(client: TestClient) -> None:
    response = client.get("/", headers={"Accept": "application/json"})
    assert response.json()["docs"] == "/docs"


def test_admin_bootstrap_requires_secret(client: TestClient) -> None:
    assert client.post("/api/v1/admin/orgs", json={"name": "Acme"}).status_code == 401
    assert (
        client.post(
            "/api/v1/admin/orgs", json={"name": "Acme"}, headers={"X-Admin-Secret": "wrong"}
        ).status_code
        == 401
    )


def test_admin_bootstrap_creates_org_and_key(client: TestClient) -> None:
    response = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN)
    assert response.status_code == 201
    body = response.json()
    assert body["raw_key"].startswith("ddl_live_")
    key = ApiKeyCreated.model_validate(body)
    whoami = client.get("/api/v1/auth/whoami", headers={"X-API-Key": key.raw_key})
    assert whoami.json()["org_name"] == "Acme"


def test_admin_issue_key_for_org_creates_second_working_key(client: TestClient) -> None:
    org = client.post("/api/v1/admin/orgs", json={"name": "Acme"}, headers=ADMIN).json()
    response = client.post(f"/api/v1/admin/orgs/{org['org_id']}/keys", headers=ADMIN)
    assert response.status_code == 201
    second_key = response.json()["raw_key"]
    whoami = client.get("/api/v1/auth/whoami", headers={"X-API-Key": second_key})
    assert whoami.json()["org_id"] == org["org_id"]


def test_admin_issue_key_for_unknown_org_is_404(client: TestClient) -> None:
    response = client.post(f"/api/v1/admin/orgs/{uuid.uuid4()}/keys", headers=ADMIN)
    assert response.status_code == 404


def test_missing_and_invalid_key_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/datasets").status_code == 401
    assert client.get("/api/v1/datasets", headers={"X-API-Key": "bogus"}).status_code == 401


def test_run_then_fetch_dataset_and_report(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    run = _run_csv(client, auth_headers)
    assert run["status"] == "succeeded"
    dataset_id = run["dataset_id"]

    listing = client.get("/api/v1/datasets", headers=auth_headers).json()
    assert [d["id"] for d in listing] == [dataset_id]

    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=auth_headers).json()
    assert dataset["records"][0]["record_key"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

    report = client.get(
        f"/api/v1/datasets/{dataset_id}/quality-report", headers=auth_headers
    ).json()
    assert report["accepted_records"] == 1

    enrichment = client.get(
        f"/api/v1/datasets/{dataset_id}/enrichment", headers=auth_headers
    ).json()
    assert enrichment["enrichment_enabled"] is False
    assert enrichment["results"][0]["status"] == "skipped_no_key"


def test_filter_records(client: TestClient, auth_headers: dict[str, str]) -> None:
    run = _run_csv(client, auth_headers)
    dataset_id = run["dataset_id"]
    filtered = client.get(
        f"/api/v1/datasets/{dataset_id}/records", params={"mw_min": 100}, headers=auth_headers
    )
    assert len(filtered.json()) == 1
    filtered = client.get(
        f"/api/v1/datasets/{dataset_id}/records", params={"mw_min": 10000}, headers=auth_headers
    )
    assert filtered.json() == []


def test_export_formats(client: TestClient, auth_headers: dict[str, str]) -> None:
    run = _run_csv(client, auth_headers)
    dataset_id = run["dataset_id"]
    csv = client.get(f"/api/v1/datasets/{dataset_id}/export", headers=auth_headers)
    assert csv.headers["content-type"].startswith("text/csv")
    jsonl = client.get(
        f"/api/v1/datasets/{dataset_id}/export", params={"format": "jsonl"}, headers=auth_headers
    )
    assert jsonl.headers["content-type"].startswith("application/x-ndjson")


def test_failed_run_reports_error(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/pipelines/run",
        json={"source": "json", "json_path": "x.json"},
        headers=auth_headers,
    )
    run_id = response.json()["id"]
    for _ in range(20):
        status = client.get(f"/api/v1/pipelines/runs/{run_id}", headers=auth_headers).json()
        if status["status"] == "failed":
            break
        time.sleep(0.05)
    assert "cannot parse JSON" in status["error"]


def test_org_isolation(
    client: TestClient, services: ApiServices, auth_headers: dict[str, str]
) -> None:
    run = _run_csv(client, auth_headers)
    dataset_id = run["dataset_id"]
    from dndlabs.core.schemas import Organization

    other_org = services.repositories.organizations.create(Organization(name="OtherCo"))
    other_key = services.auth.issue_key(other_org)
    other_headers = {"X-API-Key": other_key.raw_key}
    assert client.get(f"/api/v1/datasets/{dataset_id}", headers=other_headers).status_code == 404
    assert client.get("/api/v1/datasets", headers=other_headers).json() == []


def test_revoked_key_is_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post("/api/v1/auth/keys/revoke", headers=auth_headers).status_code == 204
    assert client.get("/api/v1/datasets", headers=auth_headers).status_code == 401


def test_privacy_delete_removes_org_data(client: TestClient, auth_headers: dict[str, str]) -> None:
    _run_csv(client, auth_headers)
    assert client.get("/api/v1/datasets", headers=auth_headers).json() != []
    assert client.delete("/api/v1/orgs/me/data", headers=auth_headers).status_code == 204
    assert client.get("/api/v1/datasets", headers=auth_headers).json() == []


def test_invalid_spec_is_422(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert (
        client.post(
            "/api/v1/pipelines/run", json={"source": "pubchem"}, headers=auth_headers
        ).status_code
        == 422
    )


def test_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    import uuid

    fake_id = str(uuid.uuid4())
    assert client.get(f"/api/v1/pipelines/runs/{fake_id}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/v1/datasets/{fake_id}", headers=auth_headers).status_code == 404
    assert (
        client.get(f"/api/v1/datasets/{fake_id}/quality-report", headers=auth_headers).status_code
        == 404
    )


def test_storage_errors_are_500(
    services: ApiServices, client: TestClient, auth_headers: dict[str, str]
) -> None:
    def boom(org_id: object) -> list[object]:
        raise StorageError("database unavailable")

    services.repositories.datasets.list_for_org = boom  # type: ignore[method-assign]
    response = client.get("/api/v1/datasets", headers=auth_headers)
    assert response.status_code == 500
    # The underlying database error message must never reach the client.
    assert response.json() == {"detail": "internal server error"}
    assert "database unavailable" not in response.text


def test_unhandled_exception_is_500_and_never_leaks_its_message(
    services: ApiServices, auth_headers: dict[str, str]
) -> None:
    def boom(org_id: object) -> list[object]:
        raise RuntimeError("some unanticipated bug, not a DndLabsError")

    services.repositories.datasets.list_for_org = boom  # type: ignore[method-assign]
    # A base-Exception handler only runs through ServerErrorMiddleware for a
    # real ASGI server; TestClient's default re-raises for debuggability, so
    # opt out of that here to exercise the actual production behavior.
    with TestClient(create_app(services), raise_server_exceptions=False) as unsafe_client:
        response = unsafe_client.get("/api/v1/datasets", headers=auth_headers)
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "unanticipated bug" not in response.text
