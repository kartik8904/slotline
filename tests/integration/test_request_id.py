import httpx


async def test_generates_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.headers["x-request-id"].startswith("req_")


async def test_keeps_valid_incoming_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "client-abc.123"})
    assert r.headers["x-request-id"] == "client-abc.123"


async def test_replaces_invalid_incoming_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id with spaces"})
    assert r.headers["x-request-id"].startswith("req_")
