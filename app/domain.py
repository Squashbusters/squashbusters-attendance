"""Pure domain logic (L3) — no database, fully unit-testable.

The single decision the kiosk makes on every scan: given a student's current
open check-in (if any), should this tap be a check-in, a check-out, or blocked
by the time guard?
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Action(str, Enum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    BLOCKED_TIME_GUARD = "blocked_time_guard"


@dataclass(frozen=True)
class Decision:
    action: Action
    minutes_since_check_in: float | None = None  # set when there's an open event


def decide_action(
    open_check_in_at: datetime | None,
    now: datetime,
    guard_minutes: int,
) -> Decision:
    """Decide what a scan means.

    * No open check-in           -> CHECK_IN
    * Open check-in, >= guard old -> CHECK_OUT
    * Open check-in, < guard old  -> BLOCKED_TIME_GUARD (prevents an accidental
                                     instant check-out from a double-tap)
    """
    if open_check_in_at is None:
        return Decision(Action.CHECK_IN)

    minutes = (now - open_check_in_at).total_seconds() / 60.0
    if minutes < guard_minutes:
        return Decision(Action.BLOCKED_TIME_GUARD, minutes_since_check_in=minutes)
    return Decision(Action.CHECK_OUT, minutes_since_check_in=minutes)
