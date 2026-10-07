"""Shared helpers: create organisations, staff and API keys through the real API."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "another-long-password"
API = "/api/v1"


def unique_email(label: str = "user") -> str:
    return f"{label}-{uuid.uuid4().hex[:12]}@example.test"


@dataclass
class Account:
    org_id: str
    user_id: str
    email: str
    password: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


AccountFactory = Callable[..., Awaitable[Account]]


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


async def login_account(
    client: httpx.AsyncClient, *, org_id: str, user_id: str, email: str, password: str
) -> Account:
    response = await login(client, email, password)
    assert response.status_code == 200, response.text
    body = response.json()
    return Account(org_id, user_id, email, password, body["access_token"], body["refresh_token"])


def make_account_factory(client: httpx.AsyncClient) -> AccountFactory:
    async def factory(
        label: str = "owner", organization_name: str | None = None, **extra: Any
    ) -> Account:
        email = unique_email(label)
        response = await client.post(
            f"{API}/auth/signup",
            json={
                "organization_name": organization_name or f"Clinic {uuid.uuid4().hex[:8]}",
                "email": email,
                "password": PASSWORD,
                **extra,
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return await login_account(
            client,
            org_id=body["organization"]["id"],
            user_id=body["user"]["id"],
            email=email,
            password=PASSWORD,
        )

    return factory


async def add_user(
    client: httpx.AsyncClient, owner: Account, *, role: str = "staff", label: str = "staff"
) -> Account:
    email = unique_email(label)
    response = await client.post(
        f"{API}/users",
        headers=owner.headers,
        json={"email": email, "password": PASSWORD, "role": role},
    )
    assert response.status_code == 201, response.text
    return await login_account(
        client,
        org_id=owner.org_id,
        user_id=response.json()["id"],
        email=email,
        password=PASSWORD,
    )


async def add_api_key(
    client: httpx.AsyncClient,
    owner: Account,
    scopes: list[str] | None = None,
    name: str = "Vaani",
) -> tuple[str, str]:
    """Returns (key_id, full_key)."""
    response = await client.post(
        f"{API}/api-keys",
        headers=owner.headers,
        json={"name": name, "scopes": scopes or ["bookings:read"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["key"]
