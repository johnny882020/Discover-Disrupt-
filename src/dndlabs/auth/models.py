"""API key generation, hashing and verification."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

#: Prefix identifying a live D&D Labs key (vs. e.g. a future "test" env).
KEY_PREFIX = "ddl_live_"
_PREFIX_LEN = 12  # "ddl_live_" + 3 random chars, enough to disambiguate without leaking the secret


def generate_key() -> tuple[str, str]:
    """Generate a new raw API key and its lookup prefix.

    Returns:
        A ``(raw_key, prefix)`` pair. ``prefix`` is safe to store/log/index;
        ``raw_key`` must never be stored and is shown to the caller exactly
        once.
    """
    secret = secrets.token_urlsafe(32)
    raw_key = f"{KEY_PREFIX}{secret}"
    prefix = raw_key[:_PREFIX_LEN]
    return raw_key, prefix


def hash_key(raw_key: str) -> str:
    """Hash a raw key for storage.

    Args:
        raw_key: The raw secret.

    Returns:
        An Argon2 hash safe to persist.
    """
    return _hasher.hash(raw_key)


def verify_key(raw_key: str, hashed_key: str) -> bool:
    """Verify a raw key against its stored hash.

    Args:
        raw_key: The raw secret presented by the caller.
        hashed_key: The stored Argon2 hash.

    Returns:
        True if the key matches.
    """
    try:
        return _hasher.verify(hashed_key, raw_key)
    except VerifyMismatchError:
        return False


def key_prefix(raw_key: str) -> str:
    """Extract the lookup prefix from a raw key.

    Args:
        raw_key: The raw key as presented by a caller.

    Returns:
        The prefix to look up in storage.
    """
    return raw_key[:_PREFIX_LEN]
