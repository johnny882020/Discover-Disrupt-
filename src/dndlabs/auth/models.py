"""API key generation, hashing and verification.

Also owns the Argon2id hasher that user passwords share.
"""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

#: Argon2id hasher shared by API keys and user passwords (argon2-cffi
#: defaults: the RFC 9106 low-memory profile, 64 MiB, t=3).
#: Not pinned, so if a library upgrade raises the defaults,
#: ``passwords.needs_rehash`` flags older password hashes and the next
#: sign-in upgrades them (API-key hashes are never re-hashed).
password_hasher = PasswordHasher()

#: Prefix identifying a live D&D Labs key (vs. e.g. a future "test" env).
KEY_PREFIX = "ddl_live_"
#: Random bytes behind ``KEY_PREFIX``: 40 bytes are 54 base64url characters.
_SECRET_BYTES = 40
#: ``KEY_PREFIX`` + 12 random characters (72 bits). The lookup prefix is
#: unique, so it must stay collision-free as keys accumulate: with 3 random
#: characters (the original length, ~262k values) collisions became likely
#: after a few hundred keys. The prefix is stored and logged, so it is not
#: secret; the 42 characters after it (248 bits) are.
_PREFIX_LEN = len(KEY_PREFIX) + 12
#: Keys issued before the longer prefix: ``KEY_PREFIX`` + 43 characters
#: (``token_urlsafe(32)``), looked up by their first 12 characters. A new key
#: is always longer (``token_urlsafe(40)`` gives 54), so the length alone
#: tells the formats apart and old keys keep working.
_LEGACY_KEY_LEN = len(KEY_PREFIX) + 43
_LEGACY_PREFIX_LEN = 12


def generate_key() -> tuple[str, str]:
    """Generate a new raw API key and its lookup prefix.

    Returns:
        A ``(raw_key, prefix)`` pair. ``prefix`` is safe to store/log/index;
        ``raw_key`` must never be stored and is shown to the caller exactly
        once.
    """
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    raw_key = f"{KEY_PREFIX}{secret}"
    return raw_key, key_prefix(raw_key)


def hash_key(raw_key: str) -> str:
    """Hash a raw key for storage.

    Args:
        raw_key: The raw secret.

    Returns:
        An Argon2 hash safe to persist.
    """
    return password_hasher.hash(raw_key)


def verify_key(raw_key: str, hashed_key: str) -> bool:
    """Verify a raw key against its stored hash.

    Args:
        raw_key: The raw secret presented by the caller.
        hashed_key: The stored Argon2 hash.

    Returns:
        True if the key matches.
    """
    try:
        return password_hasher.verify(hashed_key, raw_key)
    # A corrupt stored hash is a rejected key (401), not a server error (500),
    # as in passwords.verify_password.
    except (VerificationError, InvalidHashError):
        return False


def key_prefix(raw_key: str) -> str:
    """Extract the lookup prefix from a raw key.

    Args:
        raw_key: The raw key as presented by a caller.

    Returns:
        The prefix to look up in storage: 12 characters for a key issued
        before the longer prefix, 21 otherwise.
    """
    if len(raw_key) == _LEGACY_KEY_LEN:
        return raw_key[:_LEGACY_PREFIX_LEN]
    return raw_key[:_PREFIX_LEN]
