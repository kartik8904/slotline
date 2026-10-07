from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from slotline.api.deps import get_engine
from slotline.db import ping
from slotline.errors import ErrorCode, problem_response

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(
    request: Request, engine: Annotated[AsyncEngine, Depends(get_engine)]
) -> JSONResponse:
    """Ready when Postgres answers. Redis is reported but never required (plan C12)."""
    postgres_ok = await ping(engine)
    redis_ok = await _redis_ok(request.app.state.redis)
    checks = {"postgres": "ok" if postgres_ok else "down", "redis": "ok" if redis_ok else "down"}

    if not postgres_ok:
        return problem_response(
            request,
            503,
            ErrorCode.SERVICE_UNAVAILABLE,
            "Service unavailable",
            "Postgres is not reachable.",
            extra={"checks": checks},
        )
    return JSONResponse({"status": "ok", "checks": checks})


async def _redis_ok(client: Redis) -> bool:
    try:
        return bool(await client.ping())
    except Exception:
        return False
