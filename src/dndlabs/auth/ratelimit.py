"""Fixed-window brute-force limits, counted in the database.

Counters live in the ``rate_limits`` table (``RateLimitRepository``), not in
process memory, so a limit holds across workers, instances, restarts and
deploys. Each bucket counts events in fixed windows aligned to the Unix
epoch (``DNDLABS_RATE_LIMIT_WINDOW_SECONDS``): simple, one atomic upsert per
event, and a ``Retry-After`` that is exact. Its known weakness — up to twice
the limit in a burst straddling a window boundary — is acceptable for
brute-force limits, whose job is to cap sustained guessing.

Bucket keys carry SHA-256 digests of client IPs and emails, never the raw
values. A digest is pseudonymization, not anonymity (an IPv4 address or a
known email can be found by hashing candidates), but counters are deleted
once their window ends, so the table holds nothing older than one window.
"""

import hashlib
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from dndlabs.core.exceptions import RateLimitedError
from dndlabs.core.logging import get_logger
from dndlabs.core.protocols import RateLimitRepository

logger = get_logger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _digest(value: str) -> str:
    """SHA-256 hex digest of ``value``."""
    return hashlib.sha256(value.encode()).hexdigest()


def signin_ip_bucket(client_ip: str) -> str:
    """Bucket of sign-in attempts from one client IP (all emails).

    Args:
        client_ip: The client's IP address.

    Returns:
        The bucket key.
    """
    return f"signin-ip:{_digest(client_ip)}"


def signin_email_bucket(email: str) -> str:
    """Bucket of sign-in attempts for one email from every IP.

    It is also the key prefix of the email's per-IP buckets
    (:func:`signin_email_ip_bucket`), so clearing it as a prefix clears all
    of the email's sign-in limits at once. The digest has a fixed length, so
    the prefix never matches another email's buckets.

    Args:
        email: The normalized email.

    Returns:
        The bucket key.
    """
    return f"signin-email:{_digest(email)}"


def signin_email_ip_bucket(email: str, client_ip: str) -> str:
    """Bucket of sign-in attempts for one email from one client IP.

    Args:
        email: The normalized email.
        client_ip: The client's IP address.

    Returns:
        The bucket key.
    """
    return f"{signin_email_bucket(email)}:ip:{_digest(client_ip)}"


def auth_failure_bucket(client_ip: str) -> str:
    """Bucket of failed API-key and session-token authentications from one client IP.

    Args:
        client_ip: The client's IP address.

    Returns:
        The bucket key.
    """
    return f"auth-failure-ip:{_digest(client_ip)}"


@dataclass(frozen=True)
class Window:
    """One fixed window: every bucket touched by a request uses the same one.

    Attributes:
        now: When the request is evaluated.
        start: The window's start (inclusive).
        end: The window's end (exclusive); counters expire then.
    """

    now: datetime
    start: datetime
    end: datetime

    @property
    def retry_after_seconds(self) -> int:
        """Whole seconds until the window ends (at least 1)."""
        return max(1, math.ceil((self.end - self.now).total_seconds()))


class RateLimiter:
    """Counts events per bucket and refuses those beyond a bucket's limit."""

    def __init__(
        self,
        repository: RateLimitRepository,
        window: timedelta,
        clock: Callable[[], datetime],
    ) -> None:
        """Create the limiter.

        Args:
            repository: Where the counters are stored.
            window: Length of a fixed window.
            clock: Current-time source.
        """
        self._repository = repository
        self._window_seconds = window.total_seconds()
        self._clock = clock

    def window(self) -> Window:
        """Return the current window.

        Returns:
            The window containing the clock's current time.
        """
        now = self._clock()
        elapsed = (now - _EPOCH).total_seconds()
        start = _EPOCH + timedelta(
            seconds=math.floor(elapsed / self._window_seconds) * self._window_seconds
        )
        return Window(now=now, start=start, end=start + timedelta(seconds=self._window_seconds))

    def hit(self, bucket: str, limit: int, window: Window) -> None:
        """Count an event, refusing it if the bucket is now over its limit.

        The event is counted even when refused, so a client that keeps
        retrying stays refused until the window ends.

        Args:
            bucket: The bucket key.
            limit: Events allowed per window.
            window: The current window.

        Raises:
            RateLimitedError: If this event exceeds the limit.
        """
        if self._repository.hit(bucket, window.start, window.end) > limit:
            self._refuse(bucket, window)

    def check(self, bucket: str, limit: int, window: Window) -> None:
        """Refuse if the bucket has already reached its limit, without counting.

        Args:
            bucket: The bucket key.
            limit: Events allowed per window.
            window: The current window.

        Raises:
            RateLimitedError: If the limit is reached.
        """
        if self._repository.count(bucket, window.start) >= limit:
            self._refuse(bucket, window)

    def refund(self, bucket: str, window: Window) -> None:
        """Take back one event counted by :meth:`hit` in this window.

        Args:
            bucket: The bucket key.
            window: The current window.
        """
        self._repository.refund(bucket, window.start)

    def clear(self, bucket_prefix: str) -> None:
        """Delete every counter whose bucket starts with ``bucket_prefix``.

        Args:
            bucket_prefix: Literal bucket prefix.
        """
        self._repository.clear(bucket_prefix)

    def purge_expired(self, window: Window) -> None:
        """Delete counters whose window has ended (opportunistic housekeeping).

        Args:
            window: The current window.
        """
        self._repository.delete_expired(window.now)

    @staticmethod
    def _refuse(bucket: str, window: Window) -> None:
        """Log and raise the refusal; only the bucket's kind is logged, no digest."""
        kind = bucket.split(":", 1)[0] + ("-ip" if ":ip:" in bucket else "")
        logger.warning(
            "rate_limited",
            extra={"limit": kind, "retry_after_seconds": window.retry_after_seconds},
        )
        raise RateLimitedError(f"{kind} limit reached", window.retry_after_seconds)
