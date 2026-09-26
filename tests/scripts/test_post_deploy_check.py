from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripts.post_deploy_check import (
    DeployCheckError,
    operations,
    protected_operations,
    run_checks,
)
from sqlalchemy import text

from dndlabs.pipeline.factory import Container
from dndlabs.storage.database import create_db_engine


def test_passes_against_a_correct_deployment(client: TestClient, app: FastAPI) -> None:
    run_checks(client, expected_spec=app.openapi(), wake_timeout=0)


def test_every_protected_route_is_covered(app: FastAPI) -> None:
    protected = protected_operations(app.openapi())
    assert ("POST", "/api/v1/uploads") in protected
    assert ("POST", "/api/v1/admin/orgs") in protected
    assert ("POST", "/api/v1/auth/login") not in protected
    assert ("GET", "/api/v1/health/ready") not in protected


def test_fails_when_the_newest_migration_did_not_apply(
    client: TestClient, container: Container
) -> None:
    engine = create_db_engine(container.settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '0004'"))
    engine.dispose()
    with pytest.raises(DeployCheckError, match="readiness: 503"):
        run_checks(client, wake_timeout=0)


def test_fails_when_routes_differ_from_the_deployed_commit(
    client: TestClient, app: FastAPI
) -> None:
    expected: dict[str, Any] = app.openapi()
    expected = {**expected, "paths": {**expected["paths"], "/api/v1/new-feature": {"get": {}}}}
    with pytest.raises(DeployCheckError, match=r"missing \['GET /api/v1/new-feature'\]"):
        run_checks(client, expected_spec=expected, wake_timeout=0)


def test_fails_when_a_protected_route_is_open(app: FastAPI) -> None:
    @app.get("/api/v1/leaky", openapi_extra={"security": [{"APIKeyHeader": []}]})
    def leaky() -> dict[str, str]:
        return {"secret": "data"}

    app.openapi_schema = None
    with (
        TestClient(app) as client,
        pytest.raises(DeployCheckError, match="GET /api/v1/leaky without credentials returned 200"),
    ):
        run_checks(client, wake_timeout=0)


def test_operations_lists_method_and_path(app: FastAPI) -> None:
    assert "POST /api/v1/uploads" in operations(app.openapi())
