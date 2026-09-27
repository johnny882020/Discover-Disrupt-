"""HTTP contract of file uploads, mapping templates and upload-sourced runs."""

import time

from fastapi.testclient import TestClient

from dndlabs.api.dependencies import ApiServices
from dndlabs.core.schemas import ApiKeyCreated, Organization
from dndlabs.ingestion.uploads import UploadLimits

CSV = b"Compound,Structure,IC50,Unit\nA-1,CC(=O)Oc1ccccc1C(=O)O,12,nM\nA-2,C1CC(,3,uM\n"
MAPPING = {
    "Compound": "source_record_id",
    "Structure": "smiles",
    "IC50": "activity_value",
    "Unit": "activity_unit",
}


def _upload(client: TestClient, headers: dict[str, str], name: str = "lab.csv", data: bytes = CSV):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/uploads", files={"file": (name, data, "text/csv")}, headers=headers)


def test_upload_returns_a_preview_with_a_suggested_mapping(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = _upload(client, auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["upload"]["filename"] == "lab.csv"
    assert body["upload"]["format"] == "csv"
    assert body["columns"] == ["Compound", "Structure", "IC50", "Unit"]
    assert body["row_count"] == 2
    assert body["suggested_mapping"] == {"Structure": "smiles", "Unit": "activity_unit"}

    again = client.get(f"/api/v1/uploads/{body['upload']['id']}/preview", headers=auth_headers)
    assert again.json()["rows"] == body["rows"]


def test_upload_requires_credentials_and_rejects_bad_files(
    client: TestClient, auth_headers: dict[str, str], services: ApiServices
) -> None:
    assert _upload(client, {}).status_code == 401
    unsupported = _upload(client, auth_headers, name="report.pdf", data=b"%PDF-1.7")
    assert unsupported.status_code == 422
    assert "unsupported file type" in unsupported.json()["detail"]

    services.uploads.limits = UploadLimits(max_bytes=10)
    too_big = _upload(client, auth_headers)
    assert too_big.status_code == 422
    assert "10-byte limit" in too_big.json()["detail"]


def test_uploads_are_private_to_their_org(
    client: TestClient, auth_headers: dict[str, str], services: ApiServices
) -> None:
    upload_id = _upload(client, auth_headers).json()["upload"]["id"]
    other: ApiKeyCreated = services.auth.issue_key(
        services.repositories.organizations.create(Organization(name="OtherCo"))
    )
    other_headers = {"X-API-Key": other.raw_key}
    assert (
        client.get(f"/api/v1/uploads/{upload_id}/preview", headers=other_headers).status_code == 404
    )
    run = client.post(
        "/api/v1/pipelines/run",
        json={"source": "upload", "upload_id": upload_id, "column_mapping": MAPPING},
        headers=other_headers,
    )
    assert run.status_code == 404


def test_run_from_an_upload(client: TestClient, auth_headers: dict[str, str]) -> None:
    upload_id = _upload(client, auth_headers).json()["upload"]["id"]
    response = client.post(
        "/api/v1/pipelines/run",
        json={
            "source": "upload",
            "upload_id": upload_id,
            "column_mapping": MAPPING,
            "dataset_name": "Plate 7",
        },
        headers=auth_headers,
    )
    assert response.status_code == 202
    run_id = response.json()["id"]
    for _ in range(40):
        run = client.get(f"/api/v1/pipelines/runs/{run_id}", headers=auth_headers).json()
        if run["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert run["status"] == "succeeded", run
    dataset = client.get(f"/api/v1/datasets/{run['dataset_id']}", headers=auth_headers).json()
    assert dataset["dataset"]["name"] == "Plate 7"
    assert [r["source_record_id"] for r in dataset["records"]] == ["A-1"]
    report = client.get(
        f"/api/v1/datasets/{run['dataset_id']}/quality-report", headers=auth_headers
    ).json()
    assert report["rejected_records"] == 1


def test_upload_run_requires_a_structure_column(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    upload_id = _upload(client, auth_headers).json()["upload"]["id"]
    response = client.post(
        "/api/v1/pipelines/run",
        json={"source": "upload", "upload_id": upload_id, "column_mapping": {"Compound": "name"}},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "identifies the structure" in response.json()["detail"][0]["msg"]


def test_mapping_templates_crud_and_suggestion(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    saved = client.post(
        "/api/v1/mapping-templates",
        json={"name": "Plate reader", "mapping": MAPPING},
        headers=auth_headers,
    )
    assert saved.status_code == 201
    template_id = saved.json()["id"]

    preview = _upload(client, auth_headers).json()
    assert preview["template"]["name"] == "Plate reader"
    assert preview["suggested_mapping"] == MAPPING

    listed = client.get("/api/v1/mapping-templates", headers=auth_headers).json()
    assert [t["name"] for t in listed] == ["Plate reader"]
    invalid = client.post(
        "/api/v1/mapping-templates",
        json={"name": "x", "mapping": {"A": "name"}},
        headers=auth_headers,
    )
    assert invalid.status_code == 422

    path = f"/api/v1/mapping-templates/{template_id}"
    assert client.delete(path, headers=auth_headers).status_code == 204
    assert client.delete(path, headers=auth_headers).status_code == 404
