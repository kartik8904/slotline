from collections.abc import Callable

import httpx

from slotline.config import Settings
from slotline.main import create_app

BAD_DB = "postgresql+asyncpg://slotline:slotline@127.0.0.1:1/nope"
BAD_REDIS = "redis://127.0.0.1:1/0"


async def test_live(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_ready_reports_postgres_and_redis(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"postgres": "ok", "redis": "ok"}}


async def test_ready_503_problem_when_postgres_down(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(database_url=BAD_DB, db_connect_timeout_seconds=2)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health/ready")
    await app.state.engine.dispose()
    await app.state.redis.aclose()

    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "service_unavailable"
    assert body["checks"]["postgres"] == "down"


async def test_ready_still_200_when_redis_down(
    make_settings: Callable[..., Settings],
) -> None:
    app = create_app(make_settings(redis_url=BAD_REDIS, redis_connect_timeout_seconds=1))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/health/ready")
    await app.state.engine.dispose()
    await app.state.redis.aclose()

    assert r.status_code == 200
    assert r.json()["checks"] == {"postgres": "ok", "redis": "down"}
