from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker

from slotline.api.v1 import router as v1_router
from slotline.clock import Clock, SystemClock
from slotline.config import Settings, get_settings
from slotline.db import create_engine
from slotline.errors import register_error_handlers
from slotline.logging_config import configure_logging
from slotline.middleware.request_id import RequestIdMiddleware
from slotline.security.tokens import JwtKeyring


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    redis = Redis.from_url(
        settings.redis_url, socket_connect_timeout=settings.redis_connect_timeout_seconds
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await redis.aclose()
        await engine.dispose()

    app = FastAPI(title="Slotline", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.keyring = JwtKeyring.from_settings(settings)
    app.state.redis = redis

    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(v1_router)
    return app
