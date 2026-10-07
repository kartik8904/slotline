from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """The only place in the codebase allowed to read the wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """A controllable clock for tests."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def advance(self, delta: timedelta) -> None:
        self._at += delta
