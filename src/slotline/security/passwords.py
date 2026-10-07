"""argon2id password hashing. Hashing takes ~50 ms of CPU, so it runs off the event loop."""

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


def build_hasher() -> PasswordHasher:
    return PasswordHasher()  # argon2id with the library's RFC 9106 low-memory profile


_hasher = build_hasher()
_dummy_hash: str | None = None


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    try:
        return await asyncio.to_thread(_hasher.verify, password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


async def verify_dummy(password: str) -> None:
    """Burn the same time as a real check, so unknown, locked and inactive accounts look alike."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await hash_password("slotline-dummy-password")
    await verify_password(_dummy_hash, password)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
