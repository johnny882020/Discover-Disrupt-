import httpx
import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.ingestion.http import RetryPolicy, send_with_retries


def _policy(sleeps: list[float], retries: int = 2) -> RetryPolicy:
    return RetryPolicy(max_retries=retries, backoff_seconds=0.5, sleep=sleeps.append)


def test_retries_busy_responses_with_exponential_backoff() -> None:
    statuses = iter([503, 429, 200])
    sleeps: list[float] = []
    response = send_with_retries(lambda: httpx.Response(next(statuses)), "Svc", _policy(sleeps))
    assert response.status_code == 200
    assert sleeps == [0.5, 1.0]


def test_returns_the_last_busy_response_once_retries_are_spent() -> None:
    sleeps: list[float] = []
    response = send_with_retries(lambda: httpx.Response(503), "Svc", _policy(sleeps, 1))
    assert response.status_code == 503
    assert sleeps == [0.5]


def test_non_retryable_errors_are_returned_at_once() -> None:
    sleeps: list[float] = []
    assert send_with_retries(lambda: httpx.Response(404), "Svc", _policy(sleeps)).status_code == 404
    assert sleeps == []


def test_unreachable_service_raises_after_retries() -> None:
    def down() -> httpx.Response:
        raise httpx.ConnectError("no route")

    sleeps: list[float] = []
    with pytest.raises(IngestionError, match="Svc unreachable: no route"):
        send_with_retries(down, "Svc", _policy(sleeps, 1))
    assert sleeps == [0.5]
