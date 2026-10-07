"""Attendance service (L3 orchestration over L4).

`process_scan` is the one entry point the kiosk API (M3) calls for every tap.
It verifies the PIN, decides check-in vs check-out (with the time guard), writes
the attendance record, and returns a structured result the UI and the future
notification layer (M5) can act on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import security
from app.clock import local_now
from app.config import settings
from app.domain import Action, decide_action
from app.models import AttendanceEvent, Student
from app.photos import save_photo


class ScanStatus(str, Enum):
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    BLOCKED_TIME_GUARD = "blocked_time_guard"
    BAD_PIN = "bad_pin"
    NOT_FOUND = "not_found"
    INACTIVE = "inactive"


@dataclass
class ScanResult:
    status: ScanStatus
    student: Student | None = None
    event: AttendanceEvent | None = None
    minutes_since_check_in: float | None = None

    @property
    def ok(self) -> bool:
        return self.status in (ScanStatus.CHECKED_IN, ScanStatus.CHECKED_OUT)

    @property
    def message(self) -> str:
        name = self.student.first_name if self.student else "there"
        if self.status is ScanStatus.CHECKED_IN:
            return f"Welcome, {name}! You're checked in."
        if self.status is ScanStatus.CHECKED_OUT:
            return f"See you next time, {name}! You're checked out."
        if self.status is ScanStatus.BLOCKED_TIME_GUARD:
            mins = int(self.minutes_since_check_in or 0)
            wait = max(0, settings.time_guard_minutes - mins)
            return f"You just checked in. Please wait about {wait} more minute(s) to check out."
        if self.status is ScanStatus.BAD_PIN:
            return "That PIN doesn't match. Please try again."
        if self.status is ScanStatus.INACTIVE:
            return "This student is not active. Please see a staff member."
        return "Student not found. Please see a staff member."


def _find_open_event_today(db: Session, student_id: int, now: datetime) -> AttendanceEvent | None:
    """The student's still-open check-in from today, if any.

    Scoped to today so a forgotten (never-checked-out) event from a previous day
    doesn't turn tomorrow's arrival into a check-out — it's left open for the
    daily report to surface instead.
    """
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = (
        select(AttendanceEvent)
        .where(
            AttendanceEvent.student_id == student_id,
            AttendanceEvent.check_out_at.is_(None),
            AttendanceEvent.check_in_at >= start_of_day,
        )
        .order_by(AttendanceEvent.check_in_at.desc())
    )
    return db.execute(stmt).scalars().first()


def process_scan(
    db: Session,
    student_id: int,
    pin: str,
    now: datetime | None = None,
    session_type: str | None = None,
    photo: str | None = None,
    require_pin: bool = True,
    guard_minutes: int | None = None,
) -> ScanResult:
    """Check a student in or out.

    The kiosk calls this with the student's PIN. A signed-in staff member can
    instead call it with ``require_pin=False`` (the dashboard's manual control),
    since they're already authenticated; pass ``guard_minutes=0`` there so a
    staff correction isn't blocked by the accidental-double-tap guard.
    """
    now = now or local_now()

    student = db.get(Student, student_id)
    if student is None:
        return ScanResult(ScanStatus.NOT_FOUND)
    if not student.active:
        return ScanResult(ScanStatus.INACTIVE, student=student)
    if require_pin and not security.verify_pin(pin, student.pin_hash):
        return ScanResult(ScanStatus.BAD_PIN, student=student)

    open_event = _find_open_event_today(db, student.id, now)
    decision = decide_action(
        open_event.check_in_at if open_event else None,
        now=now,
        guard_minutes=settings.time_guard_minutes if guard_minutes is None else guard_minutes,
    )

    if decision.action is Action.BLOCKED_TIME_GUARD:
        return ScanResult(
            ScanStatus.BLOCKED_TIME_GUARD,
            student=student,
            event=open_event,
            minutes_since_check_in=decision.minutes_since_check_in,
        )

    if decision.action is Action.CHECK_IN:
        event = AttendanceEvent(
            student_id=student.id,
            site_id=student.site_id,
            check_in_at=now,
            session_type=session_type,
            check_in_photo=save_photo(photo),
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return ScanResult(ScanStatus.CHECKED_IN, student=student, event=event)

    # CHECK_OUT
    open_event.check_out_at = now
    open_event.check_out_photo = save_photo(photo)
    db.commit()
    db.refresh(open_event)
    return ScanResult(
        ScanStatus.CHECKED_OUT,
        student=student,
        event=open_event,
        minutes_since_check_in=decision.minutes_since_check_in,
    )
