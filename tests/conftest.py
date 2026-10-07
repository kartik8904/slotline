import os
from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher

from slotline.security import passwords

# Settings() needs these at import/creation time; integration tests override them.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://slotline:slotline@localhost:5432/slotline_test"
)


@pytest.fixture(scope="session", autouse=True)
def fast_password_hashing() -> Iterator[None]:
    """argon2id with production settings costs ~50 ms a hash and the suite hashes hundreds.
    Tests use the cheapest argon2id parameters; the production hasher is covered in its own test."""
    original = passwords._hasher
    passwords._hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    passwords._dummy_hash = None
    yield
    passwords._hasher = original
    passwords._dummy_hash = None
