import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.clock import FrozenClock
from slotline.models import ApiKey
from slotline.security.hashing import sha256_hex
from tests.integration.helpers import API, AccountFactory, add_api_key, add_user

KEYS = f"{API}/api-keys"


async def test_create_shows_the_key_once_and_stores_only_a_hash(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    response = await client.post(
        KEYS,
        headers=owner.headers,
        json={"name": " Vaani ", "scopes": ["bookings:read", "bookings:write", "bookings:read"]},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["key"].startswith("sl_live_")
    assert body["prefix"] == body["key"][:12]
    assert body["name"] == "Vaani"
    assert body["scopes"] == ["bookings:read", "bookings:write"]  # duplicates removed
    assert body["last_used_at"] is None and body["revoked_at"] is None

    row = (await db.execute(select(ApiKey).where(ApiKey.id == uuid.UUID(body["id"])))).scalar_one()
    assert row.key_hash == sha256_hex(body["key"])
    assert row.org_id == uuid.UUID(owner.org_id)
    assert body["key"] not in (row.key_hash, row.prefix)

    listed = await client.get(KEYS, headers=owner.headers)
    assert body["key"] not in listed.text
    assert "key" not in listed.json()["items"][0]
    assert "key_hash" not in listed.text


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x"},
        {"scopes": ["bookings:read"]},
        {"name": "x", "scopes": []},
        {"name": "x", "scopes": ["root"]},
        {"name": "  ", "scopes": ["bookings:read"]},
        {"name": "x" * 101, "scopes": ["bookings:read"]},
        {"name": "x", "scopes": ["bookings:read"], "org_id": str(uuid.uuid4())},
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, make_account: AccountFactory, body: dict[str, object]
) -> None:
    owner = await make_account()
    response = await client.post(KEYS, headers=owner.headers, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_key_authenticates_and_last_used_is_throttled(
    client: httpx.AsyncClient, make_account: AccountFactory, clock: FrozenClock
) -> None:
    owner = await make_account()
    key_id, key = await add_api_key(client, owner)

    async def last_used() -> str | None:
        items = (await client.get(KEYS, headers=owner.headers)).json()["items"]
        value: str | None = next(i["last_used_at"] for i in items if i["id"] == key_id)
        return value

    assert await last_used() is None
    assert (await client.get(f"{API}/me", headers={"X-API-Key": key})).status_code == 200
    first = await last_used()
    assert first is not None and first.endswith("Z")

    clock.advance(timedelta(seconds=30))
    await client.get(f"{API}/me", headers={"X-API-Key": key})
    assert await last_used() == first  # written at most once a minute

    clock.advance(timedelta(seconds=31))
    await client.get(f"{API}/me", headers={"X-API-Key": key})
    assert await last_used() != first


async def test_revoke(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    key_id, key = await add_api_key(client, owner)
    assert (await client.get(f"{API}/me", headers={"X-API-Key": key})).status_code == 200

    response = await client.delete(f"{KEYS}/{key_id}", headers=owner.headers)
    assert response.status_code == 204

    rejected = await client.get(f"{API}/me", headers={"X-API-Key": key})
    assert rejected.status_code == 401
    assert rejected.json()["code"] == "unauthenticated"

    revoked_at = next(
        item["revoked_at"]
        for item in (await client.get(KEYS, headers=owner.headers)).json()["items"]
        if item["id"] == key_id
    )
    assert revoked_at is not None
    assert (await client.delete(f"{KEYS}/{key_id}", headers=owner.headers)).status_code == 204
    again = next(
        item["revoked_at"]
        for item in (await client.get(KEYS, headers=owner.headers)).json()["items"]
        if item["id"] == key_id
    )
    assert again == revoked_at  # revoking twice doesn't move the timestamp


async def test_revoking_an_unknown_key_is_404(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    response = await client.delete(f"{KEYS}/{uuid.uuid4()}", headers=owner.headers)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


@pytest.mark.parametrize("bad_key", ["nope", "sl_live_", "sl_live_" + "x" * 43, "Bearer sl_live_x"])
async def test_bad_keys_are_401(client: httpx.AsyncClient, bad_key: str) -> None:
    response = await client.get(f"{API}/me", headers={"X-API-Key": bad_key})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_list_is_paginated_by_cursor(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    created = [(await add_api_key(client, owner, name=f"key-{i}"))[0] for i in range(3)]

    first = (await client.get(f"{KEYS}?limit=2", headers=owner.headers)).json()
    assert [item["id"] for item in first["items"]] == created[:2]
    assert first["next_cursor"]

    second = (
        await client.get(f"{KEYS}?limit=2&cursor={first['next_cursor']}", headers=owner.headers)
    ).json()
    assert [item["id"] for item in second["items"]] == created[2:]
    assert second["next_cursor"] is None


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc", "cursor=%25%25%25"])
async def test_list_pagination_validation(
    client: httpx.AsyncClient, make_account: AccountFactory, query: str
) -> None:
    owner = await make_account()
    response = await client.get(f"{KEYS}?{query}", headers=owner.headers)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_cursor_that_decodes_to_nothing_is_422(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    response = await client.get(f"{KEYS}?cursor=AAAA", headers=owner.headers)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "query.cursor"


async def test_only_owners_can_manage_keys(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    key_id, key = await add_api_key(client, owner)
    body = {"name": "x", "scopes": ["bookings:read"]}

    for credential in (staff.headers, {"X-API-Key": key}):
        calls: list[tuple[str, str, dict[str, Any]]] = [
            ("POST", KEYS, {"json": body}),
            ("GET", KEYS, {}),
            ("DELETE", f"{KEYS}/{key_id}", {}),
        ]
        for method, url, kwargs in calls:
            response = await client.request(method, url, headers=credential, **kwargs)
            assert response.status_code == 403, (method, url)
            assert response.json()["code"] == "forbidden"

    # And the key survived the attempt
    assert (await client.get(f"{API}/me", headers={"X-API-Key": key})).status_code == 200


async def test_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    for method, url in (("POST", KEYS), ("GET", KEYS), ("DELETE", f"{KEYS}/{uuid.uuid4()}")):
        response = await client.request(method, url)
        assert response.status_code == 401, (method, url)
