import asyncio
from collections.abc import Callable

import httpx
import pytest

from slotline.config import Settings
from slotline.main import create_app

REQUESTS = 50
POOL_SIZE = 20


@pytest.mark.concurrency
async def test_ready_survives_more_requests_than_pool_connections(
    make_settings: Callable[..., Settings],
) -> None:
    """50 simultaneous readiness checks share a 20-connection pool and all succeed."""
    app = create_app(make_settings(db_pool_size=POOL_SIZE))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(client.get("/api/v1/health/ready") for _ in range(REQUESTS))
            )
    finally:
        await app.state.engine.dispose()
        await app.state.redis.aclose()

    assert [r.status_code for r in responses] == [200] * REQUESTS
