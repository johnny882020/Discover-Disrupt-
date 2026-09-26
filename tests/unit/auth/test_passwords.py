import pytest

from dndlabs.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    check_password_policy,
    hash_password,
    needs_rehash,
    verify_against_dummy,
    verify_password,
)
from dndlabs.core.exceptions import PasswordPolicyError

EMAIL = "ada.lovelace@acme.com"


def test_hash_verifies_and_is_salted() -> None:
    first, second = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert first != second
    assert first.startswith("$argon2id$")
    assert verify_password("correct horse battery", first)
    assert not verify_password("wrong horse battery", first)
    assert not needs_rehash(first)


def test_verify_rejects_a_malformed_hash() -> None:
    assert not verify_password("anything", "not-a-hash")


def test_dummy_verification_runs_without_error() -> None:
    verify_against_dummy("whatever the caller sent")


@pytest.mark.parametrize(
    ("password", "message"),
    [
        ("short", "at least 12"),
        ("x" * (MAX_PASSWORD_LENGTH + 1), "at most"),
        ("Password1234", "too common"),
        ("zzzzzzzzzzzzzz", "too common"),
        ("Ada.Lovelace@Acme.com", "email"),
    ],
)
def test_policy_rejects(password: str, message: str) -> None:
    with pytest.raises(PasswordPolicyError, match=message):
        check_password_policy(password, EMAIL, min_length=12)


def test_policy_rejects_the_email_local_part() -> None:
    with pytest.raises(PasswordPolicyError, match="email"):
        check_password_policy("ada.lovelace", EMAIL, min_length=8)


@pytest.mark.parametrize(
    "password", ["correct horse battery", "Tr0ub4dor&3xyz", "ünïcødé pässwörd"]
)
def test_policy_accepts_long_uncommon_passwords_without_composition_rules(password: str) -> None:
    check_password_policy(password, EMAIL, min_length=12)
