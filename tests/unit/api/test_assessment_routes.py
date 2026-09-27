"""HTTP contract of the hit/lead assessment and the exported properties."""

import csv
import io

from fastapi.testclient import TestClient
from tests.unit.api.test_routes import ADMIN, _run_csv


def test_assessment_profiles_every_compound(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    dataset_id = _run_csv(client, auth_headers)["dataset_id"]

    body = client.get(f"/api/v1/datasets/{dataset_id}/assessment", headers=auth_headers).json()

    assert body["compounds"] == 1
    assert body["actives"] == 0
    assert body["potency_classes"]["unknown"] == 1  # the fixture record has no activity
    [profile] = body["profiles"]
    assert (profile["hbd"], profile["hba"], profile["lipinski_violations"]) == (1, 4, 0)
    assert profile["potency_class"] == "unknown"
    assert [c["criterion"] for c in body["criteria"]] == [
        "mw_under_500",
        "clogp_under_5",
        "lipinski",
        "rotatable_bonds_under_10",
        "tpsa_under_140",
        "tpsa_under_90",
    ]
    mw = body["criteria"][0]
    assert mw["all_compounds"] == {"passing": 1, "evaluated": 1}
    assert mw["actives"] == {"passing": 0, "evaluated": 0}


def test_export_carries_the_computed_properties(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    dataset_id = _run_csv(client, auth_headers)["dataset_id"]
    text = client.get(f"/api/v1/datasets/{dataset_id}/export", headers=auth_headers).text
    [row] = csv.DictReader(io.StringIO(text))
    assert (row["hba"], row["lipinski_violations"], row["potency_class"]) == ("4", "0", "unknown")


def test_assessment_is_scoped_to_the_org(client: TestClient, auth_headers: dict[str, str]) -> None:
    dataset_id = _run_csv(client, auth_headers)["dataset_id"]
    other = client.post("/api/v1/admin/orgs", json={"name": "Other"}, headers=ADMIN).json()
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/assessment", headers={"X-API-Key": other["raw_key"]}
    )
    assert response.status_code == 404
