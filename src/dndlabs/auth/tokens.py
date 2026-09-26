"""Opaque bearer tokens for sign-in sessions and invitations.

Tokens are 256 bits from :mod:`secrets` behind a readable type prefix. Only
their SHA-256 digest is stored: a fast, unsalted hash is sufficient for
high-entropy random values (unlike passwords) and lets storage look a token
up by an indexed equality match.
"""

import hashlib
import secrets

#: Prefix of a sign-in session token (``Authorization: Bearer ddl_sess_…``).
SESSION_TOKEN_PREFIX = "ddl_sess_"
#: Prefix of an invitation token (carried in the invitation link).
INVITATION_TOKEN_PREFIX = "ddl_inv_"


def new_token(prefix: str) -> tuple[str, str]:
    """Generate a new token and the digest to store for it.

    Args:
        prefix: The token type prefix.

    Returns:
        A ``(raw_token, digest)`` pair. ``raw_token`` is shown to its owner
        exactly once and never stored.
    """
    raw = f"{prefix}{secrets.token_urlsafe(32)}"
    return raw, token_digest(raw)


def token_digest(raw_token: str) -> str:
    """Compute the stored digest of a token.

    Args:
        raw_token: The token as presented.

    Returns:
        Its SHA-256 hex digest.
    """
    return hashlib.sha256(raw_token.encode()).hexdigest()
