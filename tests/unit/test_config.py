import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from slotline.config import DEV_JWT_KEY, DEV_JWT_KID, Settings

GOOD_KEY = "k" * 40
OTHER_KEY = "o" * 40


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Start every test from an empty environment, in a directory with no .env file."""
    for name in ("ENVIRONMENT", "JWT_KEYS", "JWT_ACTIVE_KID", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")


def _settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def test_refuses_to_start_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("ENVIRONMENT", "local")
    with pytest.raises(ValidationError):
        _settings()


def test_refuses_to_start_with_environment_unset() -> None:
    with pytest.raises(ValidationError, match="environment"):
        _settings()


def test_refuses_an_unknown_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(ValidationError, match="environment"):
        _settings()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    settings = _settings()
    assert settings.default_timezone == "Asia/Kolkata"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_and_test_fall_back_to_the_development_key(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    settings = _settings()
    assert settings.jwt_active_kid == DEV_JWT_KID
    assert settings.jwt_keys[DEV_JWT_KID].get_secret_value() == DEV_JWT_KEY


@pytest.mark.parametrize("environment", ["uat", "production"])
def test_refuses_to_start_without_real_keys_outside_local_and_test(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("ENVIRONMENT", environment)
    with pytest.raises(ValidationError, match="JWT_KEYS is required"):
        _settings()


def test_production_with_real_keys_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_KEYS", json.dumps({"2026-10": GOOD_KEY, "2026-09": OTHER_KEY}))
    monkeypatch.setenv("JWT_ACTIVE_KID", "2026-10")
    settings = _settings()
    assert settings.jwt_active_kid == "2026-10"
    assert set(settings.jwt_keys) == {"2026-10", "2026-09"}


def test_production_refuses_the_development_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_KEYS", json.dumps({"k1": DEV_JWT_KEY}))
    monkeypatch.setenv("JWT_ACTIVE_KID", "k1")
    with pytest.raises(ValidationError, match="development JWT key"):
        _settings()


def test_refuses_short_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_KEYS", json.dumps({"k1": "too-short"}))
    monkeypatch.setenv("JWT_ACTIVE_KID", "k1")
    with pytest.raises(ValidationError, match="shorter than 32 bytes"):
        _settings()


def test_active_kid_must_be_one_of_the_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "uat")
    monkeypatch.setenv("JWT_KEYS", json.dumps({"k1": GOOD_KEY}))
    monkeypatch.setenv("JWT_ACTIVE_KID", "missing")
    with pytest.raises(ValidationError, match="JWT_ACTIVE_KID"):
        _settings()

    monkeypatch.delenv("JWT_ACTIVE_KID")
    with pytest.raises(ValidationError, match="JWT_ACTIVE_KID"):
        _settings()


def test_keys_are_not_leaked_by_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_KEYS", json.dumps({"k1": GOOD_KEY}))
    monkeypatch.setenv("JWT_ACTIVE_KID", "k1")
    assert GOOD_KEY not in repr(_settings())
