"""Retrying HTTP requests to public chemistry databases (PubChem, ChEMBL)."""

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger

logger = get_logger(__name__)

#: Statuses worth retrying: rate limiting and transient server errors.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """How often and how patiently to retry a request.

    Attributes:
        max_retries: Retries after the first attempt.
        backoff_seconds: First delay; doubled after each retry.
        sleep: Sleep function (injectable for tests).
    """

    max_retries: int = 3
    backoff_seconds: float = 0.5
    sleep: Callable[[float], None] = time.sleep


def send_with_retries(
    send: Callable[[], httpx.Response], service: str, policy: RetryPolicy
) -> httpx.Response:
    """Send a request, retrying transport errors and retryable statuses.

    Args:
        send: Performs the request once.
        service: Service name for log and error messages.
        policy: Retry policy.

    Returns:
        The last response, which may still carry an error status (a
        non-retryable one, or a retryable one once retries are exhausted).

    Raises:
        IngestionError: If the service stays unreachable.
    """
    delay = policy.backoff_seconds
    for attempt in range(policy.max_retries + 1):
        try:
            response = send()
        except httpx.TransportError as exc:
            if attempt == policy.max_retries:
                raise IngestionError(f"{service} unreachable: {exc}") from exc
            logger.warning(f"{service} transport error, retrying", extra={"error": str(exc)})
        else:
            if response.status_code not in RETRYABLE_STATUS or attempt == policy.max_retries:
                return response
            logger.warning(f"{service} busy, retrying", extra={"status_code": response.status_code})
        policy.sleep(delay)
        delay *= 2
    raise IngestionError("unreachable retry state")  # pragma: no cover
