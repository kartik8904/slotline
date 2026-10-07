import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.clock import FrozenClock
from slotline.models import RefreshToken
from slotline.security.tokens import REFRESH_TOKEN_TTL
from tests.integration.helpers import (
    API,
    Account,
    AccountFactory,
    add_api_key,
    add_user,
    login,
)


async def refresh(client: httpx.AsyncClient, token: str) -> httpx.Response:
    return await client.post(f"{API}/auth/refresh", json={"refresh_token": token})


async def family_rows(db: AsyncSession, user_id: str) -> list[RefreshToken]:
    db.expire_all()
    stmt = select(RefreshToken).where(RefreshToken.user_id == uuid.UUID(user_id))
    return list((await db.execute(stmt)).scalars().all())


async def second_session(client: httpx.AsyncClient, account: Account) -> str:
    response = await login(client, account.email, account.password)
    return str(response.json()["refresh_token"])


async def test_refresh_rotates_the_token(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    response = await refresh(client, owner.refresh_token)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["refresh_token"] != owner.refresh_token
    assert body["expires_in"] == 900

    # The new access token works
    me = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200

    # Both rows are in one family; only the old one is revoked
    rows = await family_rows(db, owner.user_id)
    assert len(rows) == 2
    assert len({row.family_id for row in rows}) == 1
    assert sorted(row.revoked_at is None for row in rows) == [False, True]
    assert all(row.expires_at > row.created_at for row in rows)


async def test_reusing_a_rotated_token_revokes_the_whole_family(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    first = owner.refresh_token
    second = (await refresh(client, first)).json()["refresh_token"]
    third = (await refresh(client, second)).json()["refresh_token"]

    # An attacker (or a stale client) replays the first, already-rotated token
    replay = await refresh(client, first)
    assert replay.status_code == 401
    assert replay.json()["code"] == "unauthenticated"

    # The family is dead, including the newest token that was never used twice
    assert (await refresh(client, third)).status_code == 401
    assert (await refresh(client, second)).status_code == 401

    # And the revocation was committed even though the request failed
    rows = await family_rows(db, owner.user_id)
    assert len(rows) == 3
    assert all(row.revoked_at is not None for row in rows)


async def test_reuse_in_one_family_leaves_other_sessions_alone(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    other_session = await second_session(client, owner)
    await refresh(client, owner.refresh_token)

    assert (await refresh(client, owner.refresh_token)).status_code == 401
    assert (await refresh(client, other_session)).status_code == 200


async def test_expired_refresh_token(
    client: httpx.AsyncClient, make_account: AccountFactory, clock: FrozenClock
) -> None:
    owner = await make_account()
    clock.advance(REFRESH_TOKEN_TTL - timedelta(seconds=1))
    assert (await refresh(client, owner.refresh_token)).status_code == 200

    owner = await make_account("second")
    clock.advance(REFRESH_TOKEN_TTL)
    expired = await refresh(client, owner.refresh_token)
    assert expired.status_code == 401
    assert expired.json()["code"] == "unauthenticated"


async def test_unknown_refresh_token(client: httpx.AsyncClient) -> None:
    response = await refresh(client, "definitely-not-a-real-token")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_refresh_validation(client: httpx.AsyncClient) -> None:
    for body in ({}, {"refresh_token": ""}, {"refresh_token": "x" * 257}, {"token": "x"}):
        response = await client.post(f"{API}/auth/refresh", json=body)
        assert response.status_code == 422


async def test_deactivated_user_cannot_refresh(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    await client.delete(f"{API}/users/{staff.user_id}", headers=owner.headers)
    assert (await refresh(client, staff.refresh_token)).status_code == 401


# --- logout --------------------------------------------------------------------------------


async def logout(client: httpx.AsyncClient, account: Account, token: str) -> httpx.Response:
    return await client.post(
        f"{API}/auth/logout", headers=account.headers, json={"refresh_token": token}
    )


async def test_logout_revokes_the_session(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    rotated = (await refresh(client, owner.refresh_token)).json()["refresh_token"]

    response = await logout(client, owner, rotated)
    assert response.status_code == 204
    assert response.content == b""
    assert (await refresh(client, rotated)).status_code == 401
    assert all(row.revoked_at is not None for row in await family_rows(db, owner.user_id))


async def test_logout_is_idempotent_and_ignores_unknown_tokens(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    assert (await logout(client, owner, owner.refresh_token)).status_code == 204
    assert (await logout(client, owner, owner.refresh_token)).status_code == 204
    assert (await logout(client, owner, "never-issued")).status_code == 204


async def test_logout_leaves_other_sessions_signed_in(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    other = await second_session(client, owner)
    await logout(client, owner, owner.refresh_token)
    assert (await refresh(client, other)).status_code == 200


async def test_logout_cannot_revoke_someone_elses_token(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    alice = await make_account("alice")
    mallory = await make_account("mallory")
    assert (await logout(client, mallory, alice.refresh_token)).status_code == 204
    assert (await refresh(client, alice.refresh_token)).status_code == 200


async def test_logout_requires_a_staff_credential(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    body = {"refresh_token": owner.refresh_token}

    anonymous = await client.post(f"{API}/auth/logout", json=body)
    assert anonymous.status_code == 401

    _, key = await add_api_key(client, owner)
    with_key = await client.post(f"{API}/auth/logout", json=body, headers={"X-API-Key": key})
    assert with_key.status_code == 403
    assert with_key.json()["code"] == "forbidden"

    invalid = await client.post(f"{API}/auth/logout", json={})
    assert invalid.status_code == 401  # authentication is checked before the body
