import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.models import User
from tests.integration.helpers import (
    API,
    NEW_PASSWORD,
    PASSWORD,
    Account,
    AccountFactory,
    add_api_key,
    add_user,
    login,
    unique_email,
)
from tests.integration.test_refresh_and_logout import refresh

USERS = f"{API}/users"


async def patch(
    client: httpx.AsyncClient, owner: Account, user_id: str, **body: object
) -> httpx.Response:
    return await client.patch(f"{USERS}/{user_id}", headers=owner.headers, json=body)


async def test_owner_creates_a_staff_member_who_can_log_in(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    email = unique_email("new")
    response = await client.post(
        USERS, headers=owner.headers, json={"email": email, "password": PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "staff"  # the default
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body
    assert (await login(client, email, PASSWORD)).status_code == 200


async def test_staff_belong_to_the_owners_organisation(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner, role="owner")
    me = (await client.get(f"{API}/me", headers=staff.headers)).json()
    assert me["organization"]["id"] == owner.org_id
    assert me["role"] == "owner"


async def test_duplicate_email_is_409_even_across_organisations(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    alice, bob = await make_account("alice"), await make_account("bob")
    response = await client.post(
        USERS, headers=alice.headers, json={"email": bob.email.upper(), "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "email_exists"
    # The error doesn't reveal which organisation holds the email
    assert bob.org_id not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"password": PASSWORD},
        {"email": "bad", "password": PASSWORD},
        {"email": "a@b.test", "password": "short"},
        {"email": "a@b.test", "password": PASSWORD, "role": "admin"},
        {"email": "a@b.test", "password": PASSWORD, "org_id": str(uuid.uuid4())},
    ],
)
async def test_create_validation(
    client: httpx.AsyncClient, make_account: AccountFactory, body: dict[str, object]
) -> None:
    owner = await make_account()
    response = await client.post(USERS, headers=owner.headers, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_list_and_get_only_show_my_organisation(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner, stranger = await make_account(), await make_account("stranger")
    staff = await add_user(client, owner)

    listed = (await client.get(USERS, headers=owner.headers)).json()
    ids = [item["id"] for item in listed["items"]]
    assert ids == [owner.user_id, staff.user_id]  # oldest first
    assert stranger.user_id not in ids

    one = await client.get(f"{USERS}/{staff.user_id}", headers=owner.headers)
    assert one.status_code == 200
    assert one.json()["email"] == staff.email


async def test_list_is_paginated(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    staff = [await add_user(client, owner, label=f"s{i}") for i in range(2)]
    everyone = [owner.user_id, *(s.user_id for s in staff)]

    page_1 = (await client.get(f"{USERS}?limit=2", headers=owner.headers)).json()
    page_2 = (
        await client.get(f"{USERS}?limit=2&cursor={page_1['next_cursor']}", headers=owner.headers)
    ).json()
    assert [i["id"] for i in page_1["items"] + page_2["items"]] == everyone
    assert page_2["next_cursor"] is None


async def test_unknown_user_is_404(client: httpx.AsyncClient, make_account: AccountFactory) -> None:
    owner = await make_account()
    missing = str(uuid.uuid4())
    assert (await client.get(f"{USERS}/{missing}", headers=owner.headers)).status_code == 404
    assert (await patch(client, owner, missing, is_active=False)).status_code == 404
    assert (await client.delete(f"{USERS}/{missing}", headers=owner.headers)).status_code == 404


async def test_a_malformed_id_is_a_validation_error(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    response = await client.get(f"{USERS}/not-a-uuid", headers=owner.headers)
    assert response.status_code == 422


async def test_update_role_and_reset_password(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)

    promoted = await patch(client, owner, staff.user_id, role="owner")
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "owner"
    assert (await refresh(client, staff.refresh_token)).status_code == 401  # sessions end

    reset = await patch(client, owner, staff.user_id, password=NEW_PASSWORD)
    assert reset.status_code == 200
    assert (await login(client, staff.email, PASSWORD)).status_code == 401
    assert (await login(client, staff.email, NEW_PASSWORD)).status_code == 200


async def test_password_reset_by_an_owner_unlocks_the_account(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    for _ in range(10):
        await login(client, staff.email, "wrong-password")
    assert (await login(client, staff.email, PASSWORD)).status_code == 401  # locked

    await patch(client, owner, staff.user_id, password=NEW_PASSWORD)
    assert (await login(client, staff.email, NEW_PASSWORD)).status_code == 200


@pytest.mark.parametrize(
    "body",
    [{}, {"role": "admin"}, {"password": "short"}, {"is_active": "maybe"}, {"email": "a@b.test"}],
)
async def test_update_validation(
    client: httpx.AsyncClient, make_account: AccountFactory, body: dict[str, object]
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    response = await patch(client, owner, staff.user_id, **body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_delete_deactivates_and_cuts_off_access_immediately(
    client: httpx.AsyncClient, make_account: AccountFactory, db: AsyncSession
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    assert (await client.get(f"{API}/me", headers=staff.headers)).status_code == 200

    assert (
        await client.delete(f"{USERS}/{staff.user_id}", headers=owner.headers)
    ).status_code == 204

    # The access token is still unexpired, but the user row is checked on every request
    assert (await client.get(f"{API}/me", headers=staff.headers)).status_code == 401
    assert (await refresh(client, staff.refresh_token)).status_code == 401
    assert (await login(client, staff.email, PASSWORD)).status_code == 401

    # Deactivated, not deleted
    row = await client.get(f"{USERS}/{staff.user_id}", headers=owner.headers)
    assert row.json()["is_active"] is False
    assert (
        await client.delete(f"{USERS}/{staff.user_id}", headers=owner.headers)
    ).status_code == 204
    count = len((await db.execute(select(User.id).where(User.email == staff.email))).all())
    assert count == 1  # the email stays reserved (C1, C28)


async def test_reactivating_restores_access(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    await client.delete(f"{USERS}/{staff.user_id}", headers=owner.headers)
    assert (await patch(client, owner, staff.user_id, is_active=True)).status_code == 200
    assert (await login(client, staff.email, PASSWORD)).status_code == 200


async def test_role_change_applies_to_existing_access_tokens(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    second_owner = await add_user(client, owner, role="owner")
    assert (await client.get(USERS, headers=second_owner.headers)).status_code == 200

    await patch(client, owner, second_owner.user_id, role="staff")
    # The role is read from the database, not trusted from the token
    assert (await client.get(USERS, headers=second_owner.headers)).status_code == 403


# --- the last owner can't be removed -------------------------------------------------------


async def test_the_last_active_owner_cannot_be_demoted_deactivated_or_deleted(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    for response in (
        await patch(client, owner, owner.user_id, role="staff"),
        await patch(client, owner, owner.user_id, is_active=False),
        await client.delete(f"{USERS}/{owner.user_id}", headers=owner.headers),
    ):
        assert response.status_code == 409
        assert response.json()["code"] == "last_owner"
    assert (await client.get(f"{API}/me", headers=owner.headers)).status_code == 200


async def test_an_owner_may_step_down_when_another_owner_exists(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    await add_user(client, owner, role="owner")
    assert (await patch(client, owner, owner.user_id, role="staff")).status_code == 200


async def test_inactive_owners_do_not_count_as_owners(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    other = await add_user(client, owner, role="owner")
    await patch(client, owner, other.user_id, is_active=False)
    response = await patch(client, owner, owner.user_id, role="staff")
    assert response.status_code == 409


async def test_changing_a_staff_member_never_trips_the_owner_guard(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    assert (await patch(client, owner, staff.user_id, is_active=False)).status_code == 200


# --- access control -------------------------------------------------------------------------


async def test_only_owners_can_manage_users(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    staff = await add_user(client, owner)
    _, key = await add_api_key(client, owner)
    calls: list[tuple[str, str, dict[str, Any]]] = [
        ("POST", USERS, {"json": {"email": unique_email(), "password": PASSWORD}}),
        ("GET", USERS, {}),
        ("GET", f"{USERS}/{owner.user_id}", {}),
        ("PATCH", f"{USERS}/{owner.user_id}", {"json": {"is_active": False}}),
        ("DELETE", f"{USERS}/{owner.user_id}", {}),
    ]
    for credential in (staff.headers, {"X-API-Key": key}):
        for method, url, kwargs in calls:
            response = await client.request(method, url, headers=credential, **kwargs)
            assert response.status_code == 403, (method, url)
            assert response.json()["code"] == "forbidden"
    # Nothing changed
    assert (await client.get(f"{API}/me", headers=owner.headers)).status_code == 200


async def test_users_endpoints_require_authentication(client: httpx.AsyncClient) -> None:
    for method, url in (
        ("POST", USERS),
        ("GET", USERS),
        ("GET", f"{USERS}/{uuid.uuid4()}"),
        ("PATCH", f"{USERS}/{uuid.uuid4()}"),
        ("DELETE", f"{USERS}/{uuid.uuid4()}"),
    ):
        response = await client.request(method, url)
        assert response.status_code == 401, (method, url)


async def test_another_organisations_user_is_404_and_untouched(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    alice, bob = await make_account("alice"), await make_account("bob")
    target = f"{USERS}/{bob.user_id}"

    for response in (
        await client.get(target, headers=alice.headers),
        await client.patch(target, headers=alice.headers, json={"is_active": False}),
        await client.patch(target, headers=alice.headers, json={"password": NEW_PASSWORD}),
        await client.delete(target, headers=alice.headers),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    still_active = await client.get(target, headers=bob.headers)
    assert still_active.json()["is_active"] is True
    assert (await login(client, bob.email, PASSWORD)).status_code == 200
