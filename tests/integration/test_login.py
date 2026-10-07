import hashlib
import uuid
from datetime import timedelta

import httpx
import jwt
import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.api.deps import login_rate_limit
from slotline.clock import FrozenClock
from slotline.domain.lockout import LOCK_DURATION, MAX_FAILURES
from slotline.errors import AppError, ErrorCode
from slotline.models import RefreshToken, User
from slotline.security import passwords
from tests.integration.helpers import (
    API,
    AccountFactory,
    add_user,
    login,
)


async def lockout_row(db: AsyncSession, user_id: str) -> User:
    db.expire_all()
    return (await db.execute(select(User).where(User.id == uuid.UUID(user_id)))).scalar_one()


async def test_login_returns_tokens(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    response = await login(client, owner.email, owner.password)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    header = jwt.get_unverified_header(body["access_token"])
    assert header["kid"] == "dev" and header["alg"] == "HS256"
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sub"] == owner.user_id and claims["org"] == owner.org_id

    # Only the hash of the refresh token is stored
    stored = (
        await db.execute(
            select(RefreshToken.token_hash).where(
                RefreshToken.token_hash
                == hashlib.sha256(body["refresh_token"].encode()).hexdigest()
            )
        )
    ).all()
    assert len(stored) == 1
    assert body["refresh_token"] not in {row[0] for row in stored}


async def test_email_is_case_insensitive(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    assert (await login(client, owner.email.upper(), owner.password)).status_code == 200


async def test_wrong_password_and_unknown_email_look_identical(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    wrong = await login(client, owner.email, "not-the-password")
    unknown = await login(client, "nobody-here@example.test", "not-the-password")

    for response in (wrong, unknown):
        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        assert response.headers["www-authenticate"] == "Bearer"

    def stable(response: httpx.Response) -> dict[str, object]:
        return {k: v for k, v in response.json().items() if k != "request_id"}

    assert stable(wrong) == stable(unknown)
    assert wrong.json()["code"] == "unauthenticated"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "a@b.test"},
        {"password": "x"},
        {"email": "bad", "password": "x"},
        {"email": "a@b.test", "password": ""},
        {"email": "a@b.test", "password": "x" * 129},
    ],
)
async def test_validation(client: httpx.AsyncClient, body: dict[str, str]) -> None:
    response = await client.post(f"{API}/auth/login", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_inactive_user_cannot_log_in(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    await client.delete(f"{API}/users/{staff.user_id}", headers=owner.headers)
    response = await login(client, staff.email, staff.password)
    assert response.status_code == 401


async def test_ten_failures_lock_the_account_even_for_the_right_password(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession, clock: FrozenClock
) -> None:
    owner = await make_account()
    for _ in range(MAX_FAILURES - 1):
        assert (await login(client, owner.email, "wrong-password")).status_code == 401
    assert (await lockout_row(db, owner.user_id)).locked_until is None

    assert (await login(client, owner.email, "wrong-password")).status_code == 401
    row = await lockout_row(db, owner.user_id)
    assert row.failed_login_count == MAX_FAILURES
    assert row.locked_until == clock.now() + LOCK_DURATION

    locked_response = await login(client, owner.email, owner.password)
    assert locked_response.status_code == 401  # same answer as a wrong password (C2)
    assert locked_response.json()["code"] == "unauthenticated"

    # Attempts while locked don't extend the lock
    assert (await lockout_row(db, owner.user_id)).locked_until == clock.now() + LOCK_DURATION

    clock.advance(LOCK_DURATION - timedelta(seconds=1))
    assert (await login(client, owner.email, owner.password)).status_code == 401
    clock.advance(timedelta(seconds=1))
    assert (await login(client, owner.email, owner.password)).status_code == 200


async def test_failures_outside_the_window_do_not_add_up(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession, clock: FrozenClock
) -> None:
    owner = await make_account()
    for _ in range(MAX_FAILURES - 1):
        await login(client, owner.email, "wrong-password")
    clock.advance(timedelta(minutes=16))
    await login(client, owner.email, "wrong-password")

    row = await lockout_row(db, owner.user_id)
    assert row.failed_login_count == 1
    assert row.locked_until is None
    assert (await login(client, owner.email, owner.password)).status_code == 200


async def test_success_resets_the_counter(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    for _ in range(5):
        await login(client, owner.email, "wrong-password")
    assert (await lockout_row(db, owner.user_id)).failed_login_count == 5

    assert (await login(client, owner.email, owner.password)).status_code == 200
    row = await lockout_row(db, owner.user_id)
    assert (row.failed_login_count, row.failed_login_window_started_at) == (0, None)


async def test_login_upgrades_an_outdated_password_hash(
    client: httpx.AsyncClient,
    make_account: AccountFactory,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = await make_account()
    before = (await lockout_row(db, owner.user_id)).password_hash
    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=2, memory_cost=8, parallelism=1)
    )

    assert (await login(client, owner.email, owner.password)).status_code == 200
    after = (await lockout_row(db, owner.user_id)).password_hash
    assert after != before
    assert "t=2" in after
    assert (await login(client, owner.email, owner.password)).status_code == 200


async def test_login_goes_through_the_rate_limit_hook(
    app: FastAPI, client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    calls: list[int] = []

    async def limited() -> None:
        calls.append(1)
        raise AppError(429, ErrorCode.RATE_LIMITED, "Rate limited", headers={"Retry-After": "60"})

    app.dependency_overrides[login_rate_limit] = limited
    response = await login(client, owner.email, owner.password)
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert calls == [1]
