from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Built-in signing key for local development and tests only. Any other environment must
# configure real keys, so a forgotten variable can never fall back to a public secret.
DEV_JWT_KID = "dev"
DEV_JWT_KEY = "dev-only-insecure-signing-key-never-use-outside-local-or-test"
MIN_JWT_KEY_BYTES = 32


class Settings(BaseSettings):
    """App configuration. A missing required variable stops the app at startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "uat", "production"] = Field(
        description="Required, no default: a missing value must never mean 'local'"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: str = Field(description="postgresql+asyncpg://user:pass@host:5432/db")
    db_connect_timeout_seconds: float = 5.0
    db_pool_size: int = 10

    redis_url: str = "redis://localhost:6379/0"
    redis_connect_timeout_seconds: float = 1.0

    default_timezone: str = "Asia/Kolkata"

    # JWT signing keys by key ID (`kid`), e.g. JWT_KEYS='{"2026-10":"<32+ byte secret>"}'.
    # Rotate by adding a new kid, switching JWT_ACTIVE_KID to it, and removing the old kid
    # once the 15-minute access tokens signed with it have expired.
    jwt_keys: dict[str, SecretStr] = Field(default_factory=dict)
    jwt_active_kid: str | None = None

    @model_validator(mode="after")
    def _check_jwt_keys(self) -> Self:
        if not self.jwt_keys:
            if self.environment not in ("local", "test"):
                raise ValueError(
                    f"JWT_KEYS is required when ENVIRONMENT={self.environment}; "
                    f"each key must be at least {MIN_JWT_KEY_BYTES} bytes"
                )
            self.jwt_keys = {DEV_JWT_KID: SecretStr(DEV_JWT_KEY)}
            self.jwt_active_kid = DEV_JWT_KID
            return self

        if self.jwt_active_kid not in self.jwt_keys:
            raise ValueError("JWT_ACTIVE_KID must name one of the kids in JWT_KEYS")
        for kid, secret in self.jwt_keys.items():
            value = secret.get_secret_value()
            if len(value.encode()) < MIN_JWT_KEY_BYTES:
                raise ValueError(f"JWT key {kid!r} is shorter than {MIN_JWT_KEY_BYTES} bytes")
            if self.environment not in ("local", "test") and value == DEV_JWT_KEY:
                raise ValueError("the development JWT key is not allowed in this environment")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
