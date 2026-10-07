"""Races in the auth flows. Each request gets its own pooled connection (20-connection pool)."""

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.clock import FrozenClock, SystemClock
from slotline.config import Settings
from slotline.domain.lockout import MAX_FAILURES
from slotline.main import create_app
from slotline.models import Organization, RefreshToken, User
from tests.integration.helpers import (
    API,
    PASSWORD,
    add_user,
    login,
    make_account_factory,
    unique_email,
)

pytestmark = pytest.mark.concurrency

PARALLEL = 20


@pytest.fixture
async def wide_app(make_settings: Callable[..., Settings]) -> AsyncIterator[FastAPI]:
    application = create_app(
        make_settings(db_pool_size=PARALLEL), clock=FrozenClock(SystemClock().now())
    )
    yield application
    await application.state.engine.dispose()
    await application.state.redis.aclose()


@pytest.fixture
async def wide_client(wide_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=wide_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def wide_db(wide_app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with wide_app.state.session_factory() as session:
        yield session


async def test_parallel_refreshes_with_one_token_yield_exactly_one_winner(
    wide_client: httpx.AsyncClient, wide_db: AsyncSession
) -> None:
    owner = await make_account_factory(wide_client)()

    responses = await asyncio.gather(
        *(
            wide_client.post(f"{API}/auth/refresh", json={"refresh_token": owner.refresh_token})
            for _ in range(PARALLEL)
        )
    )

    assert Counter(r.status_code for r in responses) == {200: 1, 401: PARALLEL - 1}
    rows = (
        (
            await wide_db.execute(
                select(RefreshToken).where(RefreshToken.user_id == uuid.UUID(owner.user_id))
            )
        )
        .scalars()
        .all()
    )
    # One rotation happened (2 rows), and the losers' replay killed the winner's token too
    assert len(rows) == 2
    assert all(row.revoked_at is not None for row in rows)


async def test_parallel_wrong_passwords_count_exactly_and_lock(
    wide_client: httpx.AsyncClient, wide_db: AsyncSession
) -> None:
    owner = await make_account_factory(wide_client)()

    responses = await asyncio.gather(
        *(login(wide_client, owner.email, "wrong-password") for _ in range(PARALLEL))
    )

    assert {r.status_code for r in responses} == {401}
    row = (
        await wide_db.execute(select(User).where(User.id == uuid.UUID(owner.user_id)))
    ).scalar_one()
    # The row lock serialises attempts: no lost updates, and attempts after the lock aren't counted
    assert row.failed_login_count == MAX_FAILURES
    assert row.locked_until is not None
    assert (await login(wide_client, owner.email, PASSWORD)).status_code == 401


async def test_two_owners_cannot_demote_each_other_at_the_same_time(
    wide_client: httpx.AsyncClient, wide_db: AsyncSession
) -> None:
    for _ in range(5):
        first = await make_account_factory(wide_client)()
        second = await add_user(wide_client, first, role="owner")

        a, b = await asyncio.gather(
            wide_client.patch(
                f"{API}/users/{second.user_id}", headers=first.headers, json={"role": "staff"}
            ),
            wide_client.patch(
                f"{API}/users/{first.user_id}", headers=second.headers, json={"role": "staff"}
            ),
        )

        # One wins. The loser is stopped by the last-owner guard (409), or, if the winner had
        # already committed when it authenticated, by its own demotion (403).
        assert sorted([a.status_code, b.status_code])[0] == 200
        assert {a.status_code, b.status_code} - {200} <= {403, 409}
        wide_db.expire_all()
        active_owners = await wide_db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.org_id == uuid.UUID(first.org_id), User.role == "owner", User.is_active)
        )
        assert active_owners == 1


async def test_parallel_signups_with_one_email_create_one_organisation(
    wide_client: httpx.AsyncClient, wide_db: AsyncSession
) -> None:
    email = unique_email()
    prefix = f"Race {uuid.uuid4().hex[:8]}"

    responses = await asyncio.gather(
        *(
            wide_client.post(
                f"{API}/auth/signup",
                json={"organization_name": f"{prefix} {i}", "email": email, "password": PASSWORD},
            )
            for i in range(PARALLEL)
        )
    )

    assert Counter(r.status_code for r in responses) == {201: 1, 409: PARALLEL - 1}
    orgs = await wide_db.scalar(
        select(func.count()).select_from(Organization).where(Organization.name.like(f"{prefix}%"))
    )
    assert orgs == 1  # the losers' organisations were rolled back with them


async def test_parallel_signups_with_one_name_all_get_distinct_slugs(
    wide_client: httpx.AsyncClient,
) -> None:
    name = f"Same {uuid.uuid4().hex[:8]}"

    responses = await asyncio.gather(
        *(
            wide_client.post(
                f"{API}/auth/signup",
                json={"organization_name": name, "email": unique_email(), "password": PASSWORD},
            )
            for _ in range(PARALLEL)
        )
    )

    assert {r.status_code for r in responses} == {201}
    slugs = [r.json()["organization"]["slug"] for r in responses]
    assert len(set(slugs)) == PARALLEL
