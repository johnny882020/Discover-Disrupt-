from fastapi.testclient import TestClient

from dndlabs.api.dependencies import ApiServices
from dndlabs.core.exceptions import StorageError
from dndlabs.core.schemas import DatasetWithRecords, PipelineRun, QualityReport


def _run_pubchem(client: TestClient) -> PipelineRun:
    response = client.post("/pipelines/run", json={"source": "pubchem", "identifiers": ["2244"]})
    assert response.status_code == 202
    submitted = PipelineRun.model_validate(response.json())
    status = client.get(f"/pipelines/runs/{submitted.id}")
    assert status.status_code == 200
    return PipelineRun.model_validate(status.json())


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_run_then_fetch_dataset_and_report(client: TestClient) -> None:
    run = _run_pubchem(client)
    assert run.status == "succeeded"
    assert run.dataset_id

    listing = client.get("/datasets").json()
    assert [d["id"] for d in listing] == [run.dataset_id]

    dataset = DatasetWithRecords.model_validate(client.get(f"/datasets/{run.dataset_id}").json())
    assert dataset.records[0].record_key == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

    report = QualityReport.model_validate(
        client.get(f"/datasets/{run.dataset_id}/quality-report").json()
    )
    assert report.accepted_records == 1
    assert report.pass_rate == 1.0


def test_export_formats(client: TestClient) -> None:
    run = _run_pubchem(client)
    csv = client.get(f"/datasets/{run.dataset_id}/export")
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("record_key,")
    jsonl = client.get(f"/datasets/{run.dataset_id}/export", params={"format": "jsonl"})
    assert jsonl.headers["content-type"].startswith("application/x-ndjson")
    assert '"record_key":"BSYNRYMUTXBXSQ-UHFFFAOYSA-N"' in jsonl.text
    assert client.get(f"/datasets/{run.dataset_id}/export?format=xml").status_code == 422


def test_failed_run_reports_error(client: TestClient) -> None:
    response = client.post("/pipelines/run", json={"source": "csv", "path": "/data/x.csv"})
    assert response.status_code == 202
    run = client.get(f"/pipelines/runs/{response.json()['id']}").json()
    assert run["status"] == "failed"
    assert "cannot parse CSV" in run["error"]


def test_invalid_spec_is_422(client: TestClient) -> None:
    assert client.post("/pipelines/run", json={"source": "pubchem"}).status_code == 422
    assert client.post("/pipelines/run", json={"source": "chembl"}).status_code == 422
    bad_cid = client.post("/pipelines/run", json={"source": "pubchem", "identifiers": ["x"]})
    assert bad_cid.status_code == 422


def test_not_found(client: TestClient) -> None:
    assert client.get("/pipelines/runs/nope").status_code == 404
    assert client.get("/datasets/nope").status_code == 404
    assert client.get("/datasets/nope/quality-report").status_code == 404
    assert client.get("/datasets/nope/export").status_code == 404


def test_storage_errors_are_500(services: ApiServices, client: TestClient) -> None:
    def boom() -> list[object]:
        raise StorageError("database unavailable")

    services.repositories.datasets.list = boom  # type: ignore[method-assign]
    response = client.get("/datasets")
    assert response.status_code == 500
    assert response.json() == {"detail": "database unavailable"}


def test_ingestion_errors_are_422(services: ApiServices, client: TestClient) -> None:
    from dndlabs.core.exceptions import IngestionError

    def boom(spec: object) -> PipelineRun:
        raise IngestionError("bad source")

    services.runner.submit = boom  # type: ignore[method-assign]
    response = client.post("/pipelines/run", json={"source": "csv", "path": "x"})
    assert response.status_code == 422


def test_root_describes_service(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "D&D Labs Data API"
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"
    assert "POST /pipelines/run" in body["endpoints"]


def test_unknown_path_is_404(client: TestClient) -> None:
    assert client.get("/no-such-route").json() == {"detail": "Not Found"}
