from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration. A missing required variable stops the app at startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "uat", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = Field(description="postgresql+asyncpg://user:pass@host:5432/db")
    db_connect_timeout_seconds: float = 5.0
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = 1.0

    default_timezone: str = "Asia/Kolkata"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
