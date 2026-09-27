"""Retrying HTTP requests to public chemistry databases (PubChem, ChEMBL).

Shared by the PubChem and ChEMBL connectors and by structure resolution.
Retries wait as long as a ``429``/``503`` response's ``Retry-After`` header
asks (capped at :data:`MAX_RETRY_AFTER_SECONDS`), else back off exponentially.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger

logger = get_logger(__name__)

#: Statuses worth retrying: rate limiting and transient server errors.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Statuses whose ``Retry-After`` header is honoured (RFC 9110 defines it for
#: 503, RFC 6585 for 429).
RETRY_AFTER_STATUS = frozenset({429, 503})

#: Longest wait a ``Retry-After`` header can impose. The wait blocks the run
#: (and the operator watching it); a service asking for longer is effectively
#: down, so the wait is capped and the remaining retries decide.
MAX_RETRY_AFTER_SECONDS = 60.0


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
        wait = delay
        try:
            response = send()
        # TransportError covers connect/read timeouts and dropped connections,
        # the usual way a busy public service fails, so they are retried too.
        except httpx.TransportError as exc:
            if attempt == policy.max_retries:
                raise IngestionError(f"{service} unreachable: {exc}") from exc
            logger.warning(f"{service} transport error, retrying", extra={"error": str(exc)})
        else:
            # A non-retryable error status is returned, not raised: to a caller
            # it can be an answer (PubChem's 404 means "not found" during
            # resolution), so each caller decides what an error status means.
            if response.status_code not in RETRYABLE_STATUS or attempt == policy.max_retries:
                return response
            logger.warning(f"{service} busy, retrying", extra={"status_code": response.status_code})
            # The server's own estimate beats a guess; the exponential delay
            # still doubles, for a later attempt whose response names none.
            if response.status_code in RETRY_AFTER_STATUS:
                requested = retry_after_seconds(response)
                wait = delay if requested is None else requested
        policy.sleep(wait)
        delay *= 2
    raise IngestionError("unreachable retry state")  # pragma: no cover


def retry_after_seconds(response: httpx.Response, now: datetime | None = None) -> float | None:
    """Read a response's ``Retry-After`` header as a wait in seconds.

    Args:
        response: The response.
        now: The current time (injectable for tests); defaults to now, UTC.

    Returns:
        The wait, clamped to ``[0, MAX_RETRY_AFTER_SECONDS]``, or ``None`` if
        the header is absent or is neither delay-seconds nor an HTTP-date.
    """
    value = response.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        # An HTTP-date is always GMT; a date without a zone is read as UTC.
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - (now or datetime.now(UTC))).total_seconds()
    # float() also accepts "nan"/"inf", which are no delay at all.
    if seconds != seconds:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)
