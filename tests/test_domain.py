"""Unit tests for the pure decision logic (L3)."""
from datetime import datetime, timedelta

from app.domain import Action, decide_action

NOW = datetime(2026, 8, 2, 16, 0, 0)
GUARD = 30


def test_no_open_event_is_check_in():
    d = decide_action(None, now=NOW, guard_minutes=GUARD)
    assert d.action is Action.CHECK_IN


def test_open_event_past_guard_is_check_out():
    checked_in = NOW - timedelta(minutes=45)
    d = decide_action(checked_in, now=NOW, guard_minutes=GUARD)
    assert d.action is Action.CHECK_OUT
    assert round(d.minutes_since_check_in) == 45


def test_open_event_within_guard_is_blocked():
    checked_in = NOW - timedelta(minutes=5)
    d = decide_action(checked_in, now=NOW, guard_minutes=GUARD)
    assert d.action is Action.BLOCKED_TIME_GUARD
    assert round(d.minutes_since_check_in) == 5


def test_exactly_at_guard_boundary_allows_check_out():
    checked_in = NOW - timedelta(minutes=30)
    d = decide_action(checked_in, now=NOW, guard_minutes=GUARD)
    assert d.action is Action.CHECK_OUT
