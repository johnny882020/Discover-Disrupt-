from dndlabs.auth.models import generate_key, hash_key, key_prefix, verify_key


def test_generate_key_has_expected_prefix() -> None:
    raw, prefix = generate_key()
    assert raw.startswith("ddl_live_")
    assert prefix == raw[: len(prefix)]
    assert key_prefix(raw) == prefix


def test_the_prefix_has_twelve_random_characters_and_fits_its_column() -> None:
    prefixes = {generate_key()[1] for _ in range(200)}
    assert {len(p) for p in prefixes} == {len("ddl_live_") + 12}
    assert max(len(p) for p in prefixes) <= 32  # api_keys.prefix is String(32)
    assert len(prefixes) == 200


def test_keys_issued_before_the_longer_prefix_keep_their_lookup_prefix() -> None:
    legacy = "ddl_live_" + "A" * 43  # token_urlsafe(32), the old key format
    assert key_prefix(legacy) == "ddl_live_AAA"
    raw, prefix = generate_key()
    assert len(raw) != len(legacy)  # the formats never share a length
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


def test_a_corrupt_stored_hash_rejects_the_key() -> None:
    raw, _ = generate_key()
    assert not verify_key(raw, "not-an-argon2-hash")
