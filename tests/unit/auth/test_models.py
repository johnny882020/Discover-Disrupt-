from dndlabs.auth.models import generate_key, hash_key, key_prefix, verify_key


def test_generate_key_has_expected_prefix() -> None:
    raw, prefix = generate_key()
    assert raw.startswith("ddl_live_")
    assert prefix == raw[: len(prefix)]
    assert key_prefix(raw) == prefix


def test_hash_and_verify_roundtrip() -> None:
    raw, _ = generate_key()
    hashed = hash_key(raw)
    assert verify_key(raw, hashed)
    assert not verify_key("wrong-key", hashed)


def test_keys_are_unique() -> None:
    a, _ = generate_key()
    b, _ = generate_key()
    assert a != b
