from datetime import timedelta

import httpx
import jwt
from fastapi import Depends, FastAPI

from slotline.api.deps import require_scope
from slotline.clock import FrozenClock
from slotline.domain.principal import Principal, Scope
from slotline.security.tokens import ACCESS_TOKEN_TTL
from tests.integration.helpers import API, AccountFactory, add_api_key, add_user


async def test_missing_credentials_are_a_401_problem(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API}/me")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.json()
    assert body["code"] == "unauthenticated"
    assert body["status"] == 401
    assert body["request_id"] == response.headers["x-request-id"]


async def test_garbage_and_foreign_credentials_are_401(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    forged = jwt.encode({"sub": owner.user_id}, "x" * 64, algorithm="HS256", headers={"kid": "dev"})
    other_kid = jwt.encode(
        {"sub": owner.user_id}, "x" * 64, algorithm="HS256", headers={"kid": "x"}
    )
    for header in (
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": f"Bearer {forged}"},
        {"Authorization": f"Bearer {other_kid}"},
        {"Authorization": f"Basic {owner.access_token}"},
        {"Authorization": owner.access_token},  # no scheme
        {"X-API-Key": owner.access_token},  # a JWT is not an API key
    ):
        response = await client.get(f"{API}/me", headers=header)
        assert response.status_code == 401, header
        assert response.json()["code"] == "unauthenticated"


async def test_sending_both_credentials_is_a_400(
    client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    owner = await make_account()
    _, key = await add_api_key(client, owner)
    response = await client.get(f"{API}/me", headers={**owner.headers, "X-API-Key": key})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


async def test_expired_access_token_is_401(
    client: httpx.AsyncClient, make_account: AccountFactory, clock: FrozenClock
) -> None:
    owner = await make_account()
    clock.advance(ACCESS_TOKEN_TTL - timedelta(seconds=1))
    assert (await client.get(f"{API}/me", headers=owner.headers)).status_code == 200

    clock.advance(timedelta(seconds=1))
    expired = await client.get(f"{API}/me", headers=owner.headers)
    assert expired.status_code == 401
    assert expired.json()["code"] == "unauthenticated"

    # A refresh gets a working token again
    refreshed = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": owner.refresh_token}
    )
    token = refreshed.json()["access_token"]
    ok = await client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


async def test_tokens_never_leak_into_the_logs(
    client: httpx.AsyncClient, make_account: AccountFactory, capfd: object
) -> None:
    owner = await make_account()
    await client.get(f"{API}/me", headers=owner.headers)
    out = capfd.readouterr().out  # type: ignore[attr-defined]
    assert owner.access_token not in out
    assert owner.refresh_token not in out
    assert owner.password not in out
    assert owner.email not in out  # emails are masked to their last four characters
    assert f'"org_id": "{owner.org_id}"' in out  # but the org is on the request log line


def _scoped_app(app: FastAPI) -> FastAPI:
    @app.get("/__test/bookings-write")
    async def endpoint(
        principal: Principal = Depends(require_scope(Scope.BOOKINGS_WRITE)),  # noqa: B008
    ) -> dict[str, str]:
        return {"org_id": str(principal.org_id)}

    return app


async def test_scopes_gate_api_keys_but_not_staff(
    app: FastAPI, client: httpx.AsyncClient, make_account: AccountFactory
) -> None:
    _scoped_app(app)
    owner = await make_account()
    staff = await add_user(client, owner)
    _, reader = await add_api_key(client, owner, ["bookings:read"])
    _, writer = await add_api_key(client, owner, ["bookings:write"])
    url = "/__test/bookings-write"

    assert (await client.get(url, headers=staff.headers)).status_code == 200
    assert (await client.get(url, headers={"X-API-Key": writer})).status_code == 200
    denied = await client.get(url, headers={"X-API-Key": reader})
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"
    assert (await client.get(url)).status_code == 401


async def test_openapi_documents_both_credential_types(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    schemes = spec["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert schemes["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "Machine client key",
    }
    me_security = spec["paths"]["/api/v1/me"]["get"]["security"]
    assert {"BearerAuth": []} in me_security and {"ApiKeyAuth": []} in me_security
