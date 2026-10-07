import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.clock import FrozenClock, SystemClock
from slotline.config import Settings
from slotline.main import create_app
from tests.integration.helpers import AccountFactory, make_account_factory

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://slotline:slotline@localhost:5432/slotline_test"
)


def run_alembic(
    *args: str, database_url: str = TEST_DATABASE_URL
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


async def _ensure_test_database() -> None:
    """Create the test database if the Postgres volume predates docker/postgres/init.sql."""
    plain = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    base, _, name = plain.rpartition("/")
    conn = await asyncpg.connect(f"{base}/postgres", timeout=5)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
async def migrated_database() -> None:
    await _ensure_test_database()
    result = run_alembic("upgrade", "head")
    assert result.returncode == 0, result.stderr


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def factory(**overrides: object) -> Settings:
        values: dict[str, object] = {"database_url": TEST_DATABASE_URL, "environment": "test"}
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    return factory


@pytest.fixture
def clock() -> FrozenClock:
    """Starts at the real current time; tests move it to expire tokens and locks."""
    return FrozenClock(SystemClock().now())


@pytest.fixture
async def app(make_settings: Callable[..., Settings], clock: FrozenClock) -> AsyncIterator[FastAPI]:
    application = create_app(make_settings(), clock=clock)
    yield application
    await application.state.engine.dispose()
    await application.state.redis.aclose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def make_account(client: httpx.AsyncClient) -> AccountFactory:
    return make_account_factory(client)


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """A separate session for asserting what is really in Postgres."""
    async with app.state.session_factory() as session:
        yield session
