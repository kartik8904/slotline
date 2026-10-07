import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.domain.principal import ALL_SCOPES
from tests.integration.helpers import (
    API,
    NEW_PASSWORD,
    AccountFactory,
    add_api_key,
    add_user,
    login,
)
from tests.integration.test_refresh_and_logout import refresh, second_session


async def test_me_as_a_user(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    response = await client.get(f"{API}/me", headers=owner.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "user"
    assert body["role"] == "owner"
    assert set(body["scopes"]) == ALL_SCOPES
    assert body["user"]["email"] == owner.email
    assert body["api_key"] is None
    assert body["organization"]["id"] == owner.org_id
    assert "password_hash" not in body["user"]


async def test_me_as_a_staff_user(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    body = (await client.get(f"{API}/me", headers=staff.headers)).json()
    assert body["role"] == "staff"
    assert body["organization"]["id"] == owner.org_id


async def test_me_as_an_api_key(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    key_id, key = await add_api_key(client, owner, ["bookings:read", "availability:read"])
    response = await client.get(f"{API}/me", headers={"X-API-Key": key})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "api_key"
    assert body["role"] is None
    assert body["scopes"] == ["availability:read", "bookings:read"]
    assert body["user"] is None
    assert body["api_key"]["id"] == key_id
    assert body["organization"]["id"] == owner.org_id
    assert key not in response.text


async def test_me_requires_authentication(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/me")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


# --- POST /me/password -----------------------------------------------------------------


async def change(
    client: httpx.AsyncClient, headers: dict[str, str], current: str, new: str
) -> httpx.Response:
    return await client.post(
        f"{API}/me/password",
        headers=headers,
        json={"current_password": current, "new_password": new},
    )


async def test_change_password_signs_out_other_sessions_only(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    other_session = await second_session(client, owner)

    response = await change(client, owner.headers, owner.password, NEW_PASSWORD)
    assert response.status_code == 204

    assert (await login(client, owner.email, owner.password)).status_code == 401
    assert (await login(client, owner.email, NEW_PASSWORD)).status_code == 200
    assert (await refresh(client, other_session)).status_code == 401  # other session: revoked
    assert (await refresh(client, owner.refresh_token)).status_code == 200  # this one: kept


async def test_change_password_with_the_wrong_current_password(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    response = await change(client, owner.headers, "not-my-password", NEW_PASSWORD)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "body.current_password"
    assert (await login(client, owner.email, owner.password)).status_code == 200


async def test_wrong_current_passwords_count_towards_lockout(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    for _ in range(10):
        response = await change(client, owner.headers, "guess", NEW_PASSWORD)
        assert response.status_code == 422

    # A stolen access token can't be used to guess forever: the account is now locked
    assert (await login(client, owner.email, owner.password)).status_code == 401
    correct = await change(client, owner.headers, owner.password, NEW_PASSWORD)
    assert correct.status_code == 422


async def test_new_password_follows_the_same_length_rules(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    for bad in ("short-pw9", "x" * 129):
        response = await change(client, owner.headers, owner.password, bad)
        assert response.status_code == 422
        assert response.json()["errors"][0]["field"] == "body.new_password"
    ok = await change(client, owner.headers, owner.password, "x" * 128)
    assert ok.status_code == 204


async def test_change_password_requires_a_logged_in_user(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    body = {"current_password": owner.password, "new_password": NEW_PASSWORD}
    assert (await client.post(f"{API}/me/password", json=body)).status_code == 401
    _, key = await add_api_key(client, owner)
    with_key = await client.post(f"{API}/me/password", json=body, headers={"X-API-Key": key})
    assert with_key.status_code == 403


async def test_change_password_stores_a_new_argon2_hash(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    from slotline.models import User

    owner = await make_account()
    before = await db.scalar(select(User.password_hash).where(User.email == owner.email))
    await change(client, owner.headers, owner.password, NEW_PASSWORD)
    db.expire_all()
    after = await db.scalar(select(User.password_hash).where(User.email == owner.email))
    assert after != before and after is not None and after.startswith("$argon2id$")
