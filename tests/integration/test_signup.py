import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from slotline.errors import AppError, ErrorCode
from slotline.models import Organization, User
from tests.integration.helpers import API, PASSWORD, unique_email

SIGNUP = f"{API}/auth/signup"


def payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "organization_name": f"Clinic {uuid.uuid4().hex[:8]}",
        "email": unique_email(),
        "password": PASSWORD,
    }
    body.update(overrides)
    return body


async def test_signup_creates_an_organisation_and_its_owner(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    body = payload(email="  Owner-" + uuid.uuid4().hex[:8] + "@Example.TEST ")
    response = await client.post(SIGNUP, json=body)

    assert response.status_code == 201
    data = response.json()
    assert data["organization"]["name"] == body["organization_name"]
    assert data["organization"]["timezone"] == "Asia/Kolkata"  # C5 default
    assert data["user"]["role"] == "owner"
    assert data["user"]["is_active"] is True
    assert data["user"]["email"] == str(body["email"]).strip().lower()
    assert "password" not in str(data).lower().replace("password_hash", "")
    assert "password_hash" not in data["user"]

    org_id = uuid.UUID(data["organization"]["id"])
    org = (await db.execute(select(Organization.settings).where(Organization.id == org_id))).one()
    assert org.settings == {
        "hold_minutes": 5,
        "waitlist_offer_minutes": 15,
        "reminder_offsets_hours": [24, 2],
    }
    user = (
        await db.execute(
            select(User.org_id, User.password_hash).where(User.id == uuid.UUID(data["user"]["id"]))
        )
    ).one()
    assert user.org_id == org_id
    assert user.password_hash.startswith("$argon2id$")


async def test_signup_accepts_an_iana_timezone(client: httpx.AsyncClient) -> None:
    response = await client.post(SIGNUP, json=payload(timezone="Europe/Dublin"))
    assert response.status_code == 201
    assert response.json()["organization"]["timezone"] == "Europe/Dublin"


async def test_two_organisations_with_the_same_name_get_different_slugs(
    client: httpx.AsyncClient,
) -> None:
    name = f"Same Name {uuid.uuid4().hex[:6]}"
    first = await client.post(SIGNUP, json=payload(organization_name=name))
    second = await client.post(SIGNUP, json=payload(organization_name=name))
    assert first.status_code == second.status_code == 201
    slug_1, slug_2 = first.json()["organization"]["slug"], second.json()["organization"]["slug"]
    assert slug_1 != slug_2
    assert slug_2.startswith(slug_1)


async def test_duplicate_email_is_409_and_leaves_no_organisation_behind(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    email = unique_email()
    assert (await client.post(SIGNUP, json=payload(email=email))).status_code == 201

    name = f"Orphan {uuid.uuid4().hex[:8]}"
    response = await client.post(SIGNUP, json=payload(email=email.upper(), organization_name=name))

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "email_exists"
    count = await db.scalar(
        select(func.count()).select_from(Organization).where(Organization.name == name)
    )
    assert count == 0


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"email": "not-an-email"}, "body.email"),
        ({"email": "a@b"}, "body.email"),
        ({"email": "x" * 250 + "@example.test"}, "body.email"),
        ({"password": "short-pw9"}, "body.password"),
        ({"password": "x" * 129}, "body.password"),
        ({"timezone": "Mars/Olympus_Mons"}, "body.timezone"),
        ({"timezone": ""}, "body.timezone"),
        ({"organization_name": "   "}, "body.organization_name"),
        ({"organization_name": "x" * 101}, "body.organization_name"),
        ({"org_id": str(uuid.uuid4())}, "body.org_id"),  # the tenant never comes from the body
    ],
)
async def test_validation_errors_are_422_problem_details(
    client: httpx.AsyncClient, overrides: dict[str, object], field: str
) -> None:
    response = await client.post(SIGNUP, json=payload(**overrides))
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert field in [error["field"] for error in body["errors"]]
    assert body["request_id"]


@pytest.mark.parametrize("missing", ["organization_name", "email", "password"])
async def test_required_fields(client: httpx.AsyncClient, missing: str) -> None:
    body = payload()
    del body[missing]
    response = await client.post(SIGNUP, json=body)
    assert response.status_code == 422
    assert f"body.{missing}" in [e["field"] for e in response.json()["errors"]]


async def test_malformed_json_is_a_problem_details_error(client: httpx.AsyncClient) -> None:
    response = await client.post(
        SIGNUP, content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_signup_goes_through_the_rate_limit_hook(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from slotline.api.deps import login_rate_limit

    async def limited() -> None:
        raise AppError(429, ErrorCode.RATE_LIMITED, "Rate limited", headers={"Retry-After": "30"})

    app.dependency_overrides[login_rate_limit] = limited
    response = await client.post(SIGNUP, json=payload())
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.headers["retry-after"] == "30"
