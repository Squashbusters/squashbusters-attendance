"""Integration tests for the attendance scan service (L3 over L4)."""
from datetime import datetime, timedelta

import pytest

from app import security
from app.models import Site, Student
from app.services import ScanStatus, process_scan

NOW = datetime(2026, 8, 2, 16, 0, 0)


@pytest.fixture()
def student(db):
    site = Site(name="Boston", active=True)
    db.add(site)
    db.flush()
    s = Student(
        first_name="Maya",
        last_name="Chen",
        active=True,
        pin_hash=security.hash_pin("7382"),
        site_id=site.id,
    )
    db.add(s)
    db.commit()
    return s


def test_first_scan_checks_in(db, student):
    result = process_scan(db, student.id, "7382", now=NOW)
    assert result.status is ScanStatus.CHECKED_IN
    assert result.event.check_in_at == NOW
    assert result.event.check_out_at is None


def test_second_scan_after_guard_checks_out(db, student):
    process_scan(db, student.id, "7382", now=NOW)
    later = NOW + timedelta(minutes=40)
    result = process_scan(db, student.id, "7382", now=later)
    assert result.status is ScanStatus.CHECKED_OUT
    assert result.event.check_out_at == later


def test_immediate_re_tap_is_blocked_by_time_guard(db, student, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "time_guard_minutes", 30)
    process_scan(db, student.id, "7382", now=NOW)
    soon = NOW + timedelta(minutes=3)
    result = process_scan(db, student.id, "7382", now=soon)
    assert result.status is ScanStatus.BLOCKED_TIME_GUARD
    # still checked in — no checkout was written
    assert result.event.check_out_at is None


def test_wrong_pin_rejected_and_writes_nothing(db, student):
    result = process_scan(db, student.id, "0000", now=NOW)
    assert result.status is ScanStatus.BAD_PIN
    from app.models import AttendanceEvent

    assert db.query(AttendanceEvent).count() == 0


def test_inactive_student_rejected(db, student):
    student.active = False
    db.commit()
    result = process_scan(db, student.id, "7382", now=NOW)
    assert result.status is ScanStatus.INACTIVE


def test_unknown_student_not_found(db):
    result = process_scan(db, 9999, "7382", now=NOW)
    assert result.status is ScanStatus.NOT_FOUND


def test_stale_open_event_from_yesterday_becomes_new_check_in(db, student):
    yesterday = NOW - timedelta(days=1)
    process_scan(db, student.id, "7382", now=yesterday)  # never checked out
    result = process_scan(db, student.id, "7382", now=NOW)
    # today's arrival is a fresh check-in, not a check-out of the stale event
    assert result.status is ScanStatus.CHECKED_IN


def test_full_day_cycle_check_in_then_out(db, student):
    r1 = process_scan(db, student.id, "7382", now=NOW)
    r2 = process_scan(db, student.id, "7382", now=NOW + timedelta(hours=2))
    assert (r1.status, r2.status) == (ScanStatus.CHECKED_IN, ScanStatus.CHECKED_OUT)
    assert r2.event.id == r1.event.id  # same record, now closed
