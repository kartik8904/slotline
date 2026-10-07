from datetime import UTC, datetime, timedelta

from slotline.domain.lockout import (
    FAILURE_WINDOW,
    LOCK_DURATION,
    MAX_FAILURES,
    LockoutState,
    after_failure,
    after_success,
    is_locked,
)

T0 = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def fail_n_times(count: int, start: datetime = T0, every: timedelta = timedelta(0)) -> LockoutState:
    state = LockoutState()
    for i in range(count):
        state = after_failure(state, start + i * every)
    return state


def test_first_failure_opens_a_window() -> None:
    state = after_failure(LockoutState(), T0)
    assert state == LockoutState(failed_count=1, window_started_at=T0, locked_until=None)


def test_nine_failures_do_not_lock() -> None:
    state = fail_n_times(MAX_FAILURES - 1)
    assert state.failed_count == 9
    assert not is_locked(state, T0)


def test_tenth_failure_in_the_window_locks_for_fifteen_minutes() -> None:
    state = fail_n_times(MAX_FAILURES)
    assert state.locked_until == T0 + LOCK_DURATION
    assert is_locked(state, T0)
    assert is_locked(state, T0 + LOCK_DURATION - timedelta(seconds=1))
    assert not is_locked(state, T0 + LOCK_DURATION)


def test_failures_spread_beyond_the_window_do_not_add_up() -> None:
    # Ten failures, but one every two minutes: the window rolls over before the tenth
    state = fail_n_times(MAX_FAILURES, every=timedelta(minutes=2))
    assert state.locked_until is None
    assert state.failed_count < MAX_FAILURES


def test_a_failure_after_the_window_starts_a_new_one() -> None:
    state = fail_n_times(5)
    later = T0 + FAILURE_WINDOW
    state = after_failure(state, later)
    assert state.failed_count == 1
    assert state.window_started_at == later


def test_failure_just_inside_the_window_still_counts() -> None:
    state = fail_n_times(5)
    state = after_failure(state, T0 + FAILURE_WINDOW - timedelta(seconds=1))
    assert state.failed_count == 6
    assert state.window_started_at == T0


def test_counting_restarts_cleanly_after_a_lock_expires() -> None:
    locked = fail_n_times(MAX_FAILURES)
    after_expiry = T0 + LOCK_DURATION
    state = after_failure(locked, after_expiry)
    assert state.failed_count == 1
    assert not is_locked(state, after_expiry)


def test_success_resets_everything() -> None:
    assert after_success() == LockoutState()
    assert not is_locked(after_success(), T0)
