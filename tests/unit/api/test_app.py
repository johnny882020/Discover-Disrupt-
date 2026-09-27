"""Application factory: startup checks and the request body size limit."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from dndlabs.api.app import BODY_TOO_LARGE_DETAIL, _content_length, create_app
from dndlabs.api.dependencies import ApiServices
from dndlabs.core.config import Settings, get_settings
from dndlabs.core.exceptions import ConfigurationError


def test_the_api_refuses_to_start_without_an_admin_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DNDLABS_ADMIN_BOOTSTRAP_SECRET", raising=False)
    monkeypatch.setenv("DNDLABS_DATABASE_URL", "sqlite://")
    monkeypatch.chdir("/")  # no .env file to read one from
    get_settings.cache_clear()
    try:
        with (
            pytest.raises(ConfigurationError, match="ADMIN_BOOTSTRAP_SECRET"),
            TestClient(create_app()),
        ):
            pass
    finally:
        get_settings.cache_clear()


def _limited_app(services: ApiServices, calls: list[int]) -> FastAPI:
    """Build the app with a 2 KiB request limit and a body-reading probe route."""
    limited = replace(
        services,
        settings=Settings(
            admin_bootstrap_secret="test-admin-secret-0123456789",
            upload_max_bytes=1024,
            request_max_bytes=2048,
        ),
    )
    app = create_app(limited)

    @app.post("/probe")
    async def probe(request: Request) -> dict[str, int]:
        calls.append(1)
        return {"size": len(await request.body())}

    @app.post("/swallow")
    async def swallow(request: Request) -> JSONResponse:
        # Stands in for FastAPI's own body parsing, which turns any read
        # error into a 400: the middleware must still answer 413.
        try:
            await request.body()
        except Exception:  # noqa: BLE001 - mimics FastAPI's catch-all body read
            return JSONResponse(status_code=400, content={"detail": "bad body"})
        return JSONResponse({"ok": True})

    return app


def test_a_declared_oversized_body_is_refused_before_the_handler_runs(
    services: ApiServices,
) -> None:
    calls: list[int] = []
    with TestClient(_limited_app(services, calls)) as client:
        response = client.post("/probe", content=b"x" * 4096)
    assert response.status_code == 413
    assert response.json() == {"detail": BODY_TOO_LARGE_DETAIL}
    assert calls == []


def test_a_chunked_body_is_cut_off_once_it_passes_the_limit(services: ApiServices) -> None:
    calls: list[int] = []

    def chunks() -> Iterator[bytes]:
        for _ in range(8):
            yield b"x" * 512

    with TestClient(_limited_app(services, calls)) as client:
        # A generator makes httpx send Transfer-Encoding: chunked with no
        # Content-Length, so only the streamed byte count can catch it.
        response = client.post("/probe", content=chunks())
    assert response.status_code == 413
    assert response.json() == {"detail": BODY_TOO_LARGE_DETAIL}


def test_the_413_wins_even_when_the_app_handles_the_aborted_read(
    services: ApiServices,
) -> None:
    with TestClient(_limited_app(services, [])) as client:
        response = client.post("/swallow", content=iter([b"x" * 1500, b"x" * 1500]))
    assert response.status_code == 413
    assert response.json() == {"detail": BODY_TOO_LARGE_DETAIL}


def test_a_malformed_content_length_is_left_to_the_byte_count() -> None:
    headers = [(b"content-length", b"not-a-number")]
    assert _content_length({"type": "http", "headers": headers}) is None
    assert _content_length({"type": "http", "headers": []}) is None


def test_bodies_within_the_limit_reach_the_handler(services: ApiServices) -> None:
    calls: list[int] = []

    def chunks() -> Iterator[bytes]:
        yield b"x" * 1000
        yield b"y" * 1000

    with TestClient(_limited_app(services, calls)) as client:
        assert client.post("/probe", content=b"x" * 2048).json() == {"size": 2048}
        assert client.post("/probe", content=chunks()).json() == {"size": 2000}
    assert calls == [1, 1]


def test_an_upload_under_the_default_limit_still_succeeds(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    csv = b"smiles\nCC(=O)Oc1ccccc1C(=O)O\n" + b"CCO\n" * 50_000  # ~200 KB
    response = client.post(
        "/api/v1/uploads", files={"file": ("big.csv", csv, "text/csv")}, headers=auth_headers
    )
    assert response.status_code == 201
