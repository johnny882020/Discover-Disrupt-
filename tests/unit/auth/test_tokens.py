import hashlib

from dndlabs.auth.tokens import (
    INVITATION_TOKEN_PREFIX,
    SESSION_TOKEN_PREFIX,
    new_token,
    token_digest,
)


def test_new_token_is_prefixed_random_and_digested() -> None:
    raw, digest = new_token(SESSION_TOKEN_PREFIX)
    other, _ = new_token(SESSION_TOKEN_PREFIX)
    assert raw.startswith("ddl_sess_") and raw != other
    assert len(raw) - len(SESSION_TOKEN_PREFIX) >= 43  # 32 random bytes, base64url
    assert digest == token_digest(raw) == hashlib.sha256(raw.encode()).hexdigest()


def test_prefixes_distinguish_token_types() -> None:
    assert new_token(INVITATION_TOKEN_PREFIX)[0].startswith("ddl_inv_")
    assert SESSION_TOKEN_PREFIX != INVITATION_TOKEN_PREFIX
