from slotline.security.api_keys import KEY_PREFIX, generate_api_key, looks_like_api_key
from slotline.security.hashing import sha256_hex


def test_key_has_the_visible_prefix_and_enough_entropy() -> None:
    new = generate_api_key()
    assert new.key.startswith("sl_live_")
    assert len(new.key) >= len(KEY_PREFIX) + 43  # 32 random bytes, base64url


def test_only_the_hash_and_a_short_prefix_are_derived() -> None:
    new = generate_api_key()
    assert new.key_hash == sha256_hex(new.key)
    assert len(new.key_hash) == 64
    assert new.key.startswith(new.prefix)
    assert len(new.prefix) == 12
    assert new.key != new.prefix


def test_keys_are_unique() -> None:
    assert generate_api_key().key != generate_api_key().key


def test_looks_like_api_key() -> None:
    assert looks_like_api_key(generate_api_key().key)
    assert not looks_like_api_key("eyJhbGciOi.not.a.key")
