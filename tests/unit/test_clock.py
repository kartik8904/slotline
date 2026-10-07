from datetime import UTC, datetime, timedelta, timezone

import pytest

from slotline.clock import FrozenClock, SystemClock


def test_system_clock_is_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_frozen_clock_returns_fixed_time_and_advances() -> None:
    clock = FrozenClock(datetime(2026, 11, 3, 9, 0, tzinfo=UTC))
    assert clock.now() == datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == datetime(2026, 11, 3, 9, 5, tzinfo=UTC)
    clock.set(datetime(2026, 12, 1, tzinfo=UTC))
    assert clock.now() == datetime(2026, 12, 1, tzinfo=UTC)


def test_frozen_clock_normalises_to_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    clock = FrozenClock(datetime(2026, 11, 4, 10, 30, tzinfo=ist))
    assert clock.now() == datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert clock.now().utcoffset() == timedelta(0)


def test_frozen_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 11, 3, 9, 0))  # noqa: DTZ001
    clock = FrozenClock(datetime(2026, 11, 3, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 11, 3))  # noqa: DTZ001
