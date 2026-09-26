import pytest
import scripts.smoke_test as smoke
from fastapi.testclient import TestClient
from scripts.smoke_test import SmokeCheckError, run_smoke

from tests.scripts.conftest import ADMIN_SECRET


def _org_key(client: TestClient, name: str) -> str:
    response = client.post(
        "/api/v1/admin/orgs", json={"name": name}, headers={"X-Admin-Secret": ADMIN_SECRET}
    )
    key: str = response.raise_for_status().json()["raw_key"]
    return key


def _leftovers(client: TestClient, key: str) -> tuple[int, int, int]:
    headers = {"X-API-Key": key}
    datasets = client.get("/api/v1/datasets", headers=headers).json()
    templates = client.get("/api/v1/mapping-templates", headers=headers).json()
    members = client.get("/api/v1/auth/members", headers=headers).json()
    return len(datasets), len(templates), len(members)


def test_passes_and_leaves_nothing_behind(client: TestClient) -> None:
    key = _org_key(client, "Smoke test")
    other = _org_key(client, "Smoke test (isolation)")

    run_smoke(client, key, other, timeout=30, wake_timeout=0)

    assert _leftovers(client, key) == (0, 0, 0)


def test_refuses_an_organization_not_named_for_smoke_tests(client: TestClient) -> None:
    customer = _org_key(client, "Acme Pharma")
    other = _org_key(client, "Smoke test (isolation)")

    with pytest.raises(SmokeCheckError, match="refusing to run as organization 'Acme Pharma'"):
        run_smoke(client, customer, other, wake_timeout=0)
    assert _leftovers(client, customer) == (0, 0, 0)


def test_refuses_two_keys_of_the_same_organization(client: TestClient) -> None:
    key = _org_key(client, "Smoke test")
    with pytest.raises(SmokeCheckError, match="same organization"):
        run_smoke(client, key, key, wake_timeout=0)


def test_cleans_up_when_a_check_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    key = _org_key(client, "Smoke test")
    other = _org_key(client, "Smoke test (isolation)")

    def leaked(*_: object) -> None:
        raise SmokeCheckError("org isolation: dataset listed for another org")

    monkeypatch.setattr(smoke, "_check_isolation", leaked)
    with pytest.raises(SmokeCheckError, match="org isolation"):
        run_smoke(client, key, other, timeout=30, wake_timeout=0)
    assert _leftovers(client, key) == (0, 0, 0)
