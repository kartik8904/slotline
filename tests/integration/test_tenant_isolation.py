"""Tenant isolation, generated from the OpenAPI spec so a new route can't skip the check.

For every operation that takes an ID in its path, an owner of organisation A calls it with
organisation B's ID and must get 404 (never 403, which would confirm the ID exists).

Adding a route:
  * ID in the path: register the parameter name in `ORG_B_IDS`; give a PATCH/POST/PUT a valid
    body in `SAMPLE_BODIES`. Until you do, this module fails, naming the route.
  * No ID in the path (create, list, public, acts-on-the-caller): add it to `NO_PATH_ID` with the
    reason it can't reach another tenant's data. Stale entries fail too.
  * IDs in the body or query (later sessions): extend `probe` the same way and note it here.
"""

import uuid
from typing import Any

import httpx
import pytest

from slotline.config import Settings
from slotline.main import create_app
from tests.integration.helpers import API, Account, AccountFactory, add_api_key, add_user

HTTP_METHODS = ("get", "post", "put", "patch", "delete")

# Operations with no ID in the path, and why that is safe.
NO_PATH_ID: dict[tuple[str, str], str] = {
    ("GET", f"{API}/health/live"): "public",
    ("GET", f"{API}/health/ready"): "public",
    ("POST", f"{API}/auth/signup"): "public; creates a new tenant",
    ("POST", f"{API}/auth/login"): "public; the tenant comes from the user found by email",
    ("POST", f"{API}/auth/refresh"): "public; the tenant comes from the token",
    ("POST", f"{API}/auth/logout"): "acts on the caller's own token (checked in test_logout)",
    ("GET", f"{API}/me"): "describes the caller",
    ("POST", f"{API}/me/password"): "acts on the caller",
    ("POST", f"{API}/api-keys"): "creates in the caller's org",
    ("GET", f"{API}/api-keys"): "listing is filtered by the caller's org (see leak test below)",
    ("POST", f"{API}/users"): "creates in the caller's org",
    ("GET", f"{API}/users"): "listing is filtered by the caller's org (see leak test below)",
}

# Path-parameter name -> a fixture key holding organisation B's ID for it.
ORG_B_IDS = {"user_id": "user_id", "key_id": "key_id"}

# Valid request bodies for operations that need one, so validation (422) can't mask a 404.
SAMPLE_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", f"{API}/users/{{user_id}}"): {"is_active": False},
}


class UnregisteredRoute(AssertionError):
    pass


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for path, item in spec["paths"].items():
        for method in HTTP_METHODS:
            if method in item:
                found.append((method.upper(), path, item[method]))
    return found


def path_params(operation: dict[str, Any]) -> list[str]:
    return [p["name"] for p in operation.get("parameters", []) if p["in"] == "path"]


def resolve(
    method: str, path: str, operation: dict[str, Any], org_b: dict[str, str]
) -> tuple[str, dict[str, Any] | None]:
    """The URL (with org B's IDs filled in) and body to probe an operation with."""
    url = path
    for name in path_params(operation):
        if name not in ORG_B_IDS:
            raise UnregisteredRoute(
                f"{method} {path} takes {{{name}}}: add it to ORG_B_IDS and the org_b fixture"
            )
        url = url.replace(f"{{{name}}}", org_b[ORG_B_IDS[name]])
    body = None
    if "requestBody" in operation:
        if (method, path) not in SAMPLE_BODIES:
            raise UnregisteredRoute(f"{method} {path} has a body: add a valid one to SAMPLE_BODIES")
        body = SAMPLE_BODIES[(method, path)]
    return url, body


def _spec() -> dict[str, Any]:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@localhost/unused", environment="test"
    )
    return create_app(settings).openapi()


SPEC = _spec()
WITH_PATH_IDS = [(m, p, op) for m, p, op in operations(SPEC) if path_params(op)]
WITHOUT_PATH_IDS = {(m, p) for m, p, op in operations(SPEC) if not path_params(op)}


@pytest.fixture
async def org_a(make_account: AccountFactory) -> Account:
    return await make_account("org-a")


@pytest.fixture
async def org_b(client: httpx.AsyncClient, make_account: AccountFactory) -> dict[str, str]:
    owner = await make_account("org-b")
    staff = await add_user(client, owner)
    key_id, _ = await add_api_key(client, owner)
    return {
        "owner_id": owner.user_id,
        "user_id": staff.user_id,
        "key_id": key_id,
        "token": owner.access_token,
    }


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    WITH_PATH_IDS,
    ids=[f"{m} {p}" for m, p, _ in WITH_PATH_IDS],
)
async def test_org_a_gets_404_for_org_b_ids(
    client: httpx.AsyncClient,
    org_a: Account,
    org_b: dict[str, str],
    method: str,
    path: str,
    operation: dict[str, Any],
) -> None:
    url, body = resolve(method, path, operation, org_b)

    response = await client.request(method, url, headers=org_a.headers, json=body)

    assert response.status_code == 404, f"{method} {url} -> {response.status_code} {response.text}"
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"

    # Org B's data is exactly as it was
    b_headers = {"Authorization": f"Bearer {org_b['token']}"}
    user = await client.get(f"{API}/users/{org_b['user_id']}", headers=b_headers)
    assert user.json()["is_active"] is True
    keys = (await client.get(f"{API}/api-keys", headers=b_headers)).json()["items"]
    assert [k["revoked_at"] for k in keys] == [None]


def test_every_operation_without_a_path_id_is_acknowledged() -> None:
    unacknowledged = WITHOUT_PATH_IDS - NO_PATH_ID.keys()
    stale = NO_PATH_ID.keys() - WITHOUT_PATH_IDS
    assert not unacknowledged, f"new routes need an entry in NO_PATH_ID: {sorted(unacknowledged)}"
    assert not stale, f"NO_PATH_ID lists routes that no longer exist: {sorted(stale)}"


def test_the_scaffold_probes_something() -> None:
    assert len(WITH_PATH_IDS) >= 4  # users: get, patch, delete; api-keys: delete


def test_a_new_route_with_an_unregistered_id_fails_the_scaffold() -> None:
    spec = {
        "paths": {
            "/api/v1/widgets/{widget_id}": {
                "get": {"parameters": [{"name": "widget_id", "in": "path", "required": True}]}
            }
        }
    }
    ((method, path, operation),) = operations(spec)
    with pytest.raises(UnregisteredRoute, match="widget_id"):
        resolve(method, path, operation, {})


def test_a_new_route_with_a_body_but_no_sample_fails_the_scaffold() -> None:
    operation = {
        "parameters": [{"name": "user_id", "in": "path", "required": True}],
        "requestBody": {},
    }
    with pytest.raises(UnregisteredRoute, match="SAMPLE_BODIES"):
        resolve("PUT", f"{API}/users/{{user_id}}", operation, {"user_id": str(uuid.uuid4())})


async def test_list_endpoints_never_include_another_organisations_rows(
    client: httpx.AsyncClient, org_a: Account, org_b: dict[str, str]
) -> None:
    users = (await client.get(f"{API}/users", headers=org_a.headers)).json()["items"]
    keys = (await client.get(f"{API}/api-keys", headers=org_a.headers)).json()["items"]

    assert {u["id"] for u in users} == {org_a.user_id}
    assert keys == []  # org B has a key, org A has none
    assert org_b["key_id"] not in str(keys)
