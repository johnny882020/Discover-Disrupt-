"""User password hashing and the password policy.

The policy follows NIST SP 800-63B: a minimum length and a screen against
commonly used and context-specific passwords, with no composition rules and
no forced periodic rotation.
"""

from functools import lru_cache

from argon2.exceptions import InvalidHashError, VerificationError

from dndlabs.auth.models import password_hasher
from dndlabs.core.exceptions import PasswordPolicyError

#: Upper bound on password length (bounds hashing cost; NIST requires >= 64).
MAX_PASSWORD_LENGTH = 128

# Commonly used passwords that satisfy the minimum length, compared
# case-insensitively. A screen, not a breach corpus.
_COMMON_PASSWORDS = frozenset(
    {
        "123456789012",
        "1234567890123",
        "12345678901234",
        "123456789012345",
        "1234567890123456",
        "aaaaaaaaaaaa",
        "abcdefghijkl",
        "abc123abc123",
        "abcd1234abcd",
        "adminadmin123",
        "iloveyou1234",
        "letmein12345",
        "passw0rd1234",
        "password1234",
        "password12345",
        "password123456",
        "passwordpassword",
        "qwerty123456",
        "qwertyuiop123",
        "qwertyuiopasdf",
        "welcome12345",
        "changeme1234",
        "freetier2026",
    }
)


def check_password_policy(password: str, email: str, min_length: int) -> None:
    """Reject a password that does not meet the policy.

    Args:
        password: The candidate password.
        email: The account's email (the password must not be derived from it).
        min_length: Minimum number of characters.

    Raises:
        PasswordPolicyError: With a message safe to show the user.
    """
    if len(password) < min_length:
        raise PasswordPolicyError(f"password must be at least {min_length} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at most {MAX_PASSWORD_LENGTH} characters")
    lowered = password.lower()
    local_part = email.split("@", 1)[0].lower()
    if lowered in _COMMON_PASSWORDS or len(set(lowered)) == 1:
        raise PasswordPolicyError("password is too common; choose a less predictable one")
    if lowered in (email.lower(), local_part):
        raise PasswordPolicyError("password must not be your email address")


def hash_password(password: str) -> str:
    """Hash a password for storage.

    Args:
        password: The plaintext password.

    Returns:
        An Argon2id hash.
    """
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its stored hash.

    Args:
        password: The plaintext password presented.
        password_hash: The stored Argon2 hash.

    Returns:
        True if the password matches.
    """
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash uses outdated parameters and should be upgraded.

    Args:
        password_hash: The stored Argon2 hash.

    Returns:
        True if it should be re-hashed on the next successful sign-in.
    """
    return password_hasher.check_needs_rehash(password_hash)


def verify_against_dummy(password: str) -> None:
    """Spend the same work as a real verification, for unknown accounts.

    Called when a sign-in names an email with no account, so the response
    time does not reveal whether the account exists.

    Args:
        password: The plaintext password presented.
    """
    verify_password(password, _dummy_hash())


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A valid hash of a fixed throwaway value, computed once."""
    return password_hasher.hash("dndlabs-dummy-password-for-timing")
