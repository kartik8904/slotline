import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from slotline.errors import AppError, ErrorCode


class Body(BaseModel):
    name: str
    count: int


def _add_routes(app: FastAPI) -> None:
    @app.post("/_test/validate")
    async def validate(body: Body) -> Body:
        return body

    @app.get("/_test/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/_test/conflict")
    async def conflict() -> None:
        raise AppError(409, ErrorCode.SLOT_UNAVAILABLE, "Slot unavailable", "Taken.")


async def test_unknown_route_is_not_found_problem(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "not_found"
    assert body["type"] == "https://slotline.dev/errors/not_found"
    assert body["request_id"] == r.headers["x-request-id"]


async def test_validation_error_lists_fields(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add_routes(app)
    r = await client.post("/_test/validate", json={"name": 1})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert {e["field"] for e in body["errors"]} == {"body.name", "body.count"}


async def test_app_error_maps_to_problem(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add_routes(app)
    r = await client.get("/_test/conflict")
    assert r.status_code == 409
    assert r.json()["code"] == "slot_unavailable"
    assert r.json()["detail"] == "Taken."


async def test_unhandled_exception_hides_internals(app: FastAPI, client: httpx.AsyncClient) -> None:
    _add_routes(app)
    r = await client.get("/_test/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["code"] == "internal_error"
    assert "secret internal detail" not in r.text
    assert "Traceback" not in r.text
    assert body["request_id"] == r.headers["x-request-id"]
