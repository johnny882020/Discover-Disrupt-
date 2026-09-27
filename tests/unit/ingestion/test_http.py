from datetime import UTC, datetime

import httpx
import pytest

from dndlabs.core.exceptions import IngestionError
from dndlabs.ingestion.http import (
    MAX_RETRY_AFTER_SECONDS,
    RetryPolicy,
    retry_after_seconds,
    send_with_retries,
)


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


def test_retry_after_seconds_replaces_the_backoff() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(503),
            httpx.Response(200),
        ]
    )
    sleeps: list[float] = []
    response = send_with_retries(lambda: next(responses), "Svc", _policy(sleeps))
    assert response.status_code == 200
    # The header's 3 s first; the next busy response has none, so the
    # exponential delay (already doubled) applies.
    assert sleeps == [3.0, 1.0]


def test_retry_after_is_capped() -> None:
    responses = iter([httpx.Response(503, headers={"Retry-After": "86400"}), httpx.Response(200)])
    sleeps: list[float] = []
    send_with_retries(lambda: next(responses), "Svc", _policy(sleeps))
    assert sleeps == [MAX_RETRY_AFTER_SECONDS]


def test_retry_after_is_ignored_on_other_statuses() -> None:
    responses = iter([httpx.Response(502, headers={"Retry-After": "7"}), httpx.Response(200)])
    sleeps: list[float] = []
    send_with_retries(lambda: next(responses), "Svc", _policy(sleeps))
    assert sleeps == [0.5]


def test_unparsable_retry_after_falls_back_to_backoff() -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "soon"}), httpx.Response(200)])
    sleeps: list[float] = []
    send_with_retries(lambda: next(responses), "Svc", _policy(sleeps))
    assert sleeps == [0.5]


NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("5", 5.0),
        ("0", 0.0),
        ("-4", 0.0),
        ("1.5", 1.5),
        ("Sun, 27 Sep 2026 12:00:10 GMT", 10.0),
        ("Sun, 27 Sep 2026 11:59:00 GMT", 0.0),
        ("Mon, 28 Sep 2026 12:00:00 GMT", MAX_RETRY_AFTER_SECONDS),
        ("nan", None),
        ("later", None),
        ("", None),
    ],
)
def test_retry_after_seconds_parses_seconds_and_http_dates(
    header: str, expected: float | None
) -> None:
    response = httpx.Response(429, headers={"Retry-After": header})
    assert retry_after_seconds(response, now=NOW) == expected


def test_missing_retry_after_is_none() -> None:
    assert retry_after_seconds(httpx.Response(429)) is None
