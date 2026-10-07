import pytest
from pydantic import ValidationError

from slotline.config import Settings


def test_refuses_to_start_without_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(str(tmp_path))  # no .env here
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.default_timezone == "Asia/Kolkata"
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
