"""Account lockout (plan C2): 10 failures within 15 minutes lock the account for 15 minutes."""

from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_FAILURES = 10
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_DURATION = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class LockoutState:
    failed_count: int = 0
    window_started_at: datetime | None = None
    locked_until: datetime | None = None


def is_locked(state: LockoutState, now: datetime) -> bool:
    return state.locked_until is not None and state.locked_until > now


def after_failure(state: LockoutState, now: datetime) -> LockoutState:
    """The state after one more wrong password. The caller skips this while locked."""
    window_open = (
        state.window_started_at is not None and now - state.window_started_at < FAILURE_WINDOW
    )
    count = state.failed_count + 1 if window_open else 1
    started = state.window_started_at if window_open else now
    locked_until = now + LOCK_DURATION if count >= MAX_FAILURES else state.locked_until
    return LockoutState(count, started, locked_until)


def after_success() -> LockoutState:
    return LockoutState()
