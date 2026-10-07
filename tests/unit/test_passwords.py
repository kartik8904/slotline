import pytest
from argon2 import PasswordHasher

from slotline.security import passwords


def test_production_hasher_is_argon2id() -> None:
    hasher = passwords.build_hasher()
    hashed = hasher.hash("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert hasher.verify(hashed, "correct horse battery")


async def test_hash_and_verify_round_trip() -> None:
    hashed = await passwords.hash_password("s3cret-passw0rd")
    assert "s3cret" not in hashed
    assert await passwords.verify_password(hashed, "s3cret-passw0rd")
    assert not await passwords.verify_password(hashed, "wrong-passw0rd")


async def test_same_password_gets_a_different_salt_each_time() -> None:
    assert await passwords.hash_password("same-password-1") != await passwords.hash_password(
        "same-password-1"
    )


async def test_garbage_hash_is_a_failed_check_not_an_error() -> None:
    assert not await passwords.verify_password("not-a-hash", "anything")


async def test_verify_dummy_runs_and_caches_its_hash() -> None:
    await passwords.verify_dummy("whatever")
    first = passwords._dummy_hash
    assert first is not None
    await passwords.verify_dummy("whatever")
    assert passwords._dummy_hash == first


def test_needs_rehash_when_parameters_are_weaker_than_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("pw")
    assert not passwords.needs_rehash(old_hash)
    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=2, memory_cost=8, parallelism=1)
    )
    assert passwords.needs_rehash(old_hash)
