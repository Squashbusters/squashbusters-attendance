"""Tests for the daily report / dashboard reporting queries (M4)."""
from datetime import date, datetime, timedelta

import pytest

from app import security
from app.models import Guardian, Program, Site, Student
from app.reporting import get_daily_rows, get_daily_summary
from app.services import process_scan

DAY = date(2026, 8, 2)
MORNING = datetime(2026, 8, 2, 9, 0, 0)


@pytest.fixture()
def site(db):
    s = Site(name="Boston", active=True)
    db.add(s)
    db.flush()
    return s


def _student(db, site, first, program_name, email):
    prog = Program(name=program_name)
    db.add(prog)
    db.flush()
    s = Student(
        first_name=first, last_name="Test", active=True,
        pin_hash=security.hash_pin("7382"), site_id=site.id, program_id=prog.id,
    )
    db.add(s)
    db.flush()
    db.add(Guardian(student_id=s.id, email=email))
    db.commit()
    return s


def test_summary_counts_present_still_in_and_checked_out(db, site):
    a = _student(db, site, "Aisha", "Middle School", "a@example.com")
    b = _student(db, site, "Ben", "High School", "b@example.com")

    # Aisha checks in and out; Ben checks in and stays.
    process_scan(db, a.id, "7382", now=MORNING)
    process_scan(db, a.id, "7382", now=MORNING + timedelta(hours=2))
    process_scan(db, b.id, "7382", now=MORNING)

    summary = get_daily_summary(db, DAY)
    assert summary["present"] == 2
    assert summary["still_in"] == 1
    assert summary["checked_out"] == 1
    assert summary["missing_email"] == 0
    assert summary["by_program"] == {"Middle School": 1, "High School": 1}


def test_missing_email_is_counted(db, site):
    s = _student(db, site, "NoEmail", "Middle School", None)
    process_scan(db, s.id, "7382", now=MORNING)
    summary = get_daily_summary(db, DAY)
    assert summary["missing_email"] == 1


def test_daily_rows_have_duration_and_status(db, site):
    a = _student(db, site, "Aisha", "Middle School", "a@example.com")
    process_scan(db, a.id, "7382", now=MORNING)
    process_scan(db, a.id, "7382", now=MORNING + timedelta(minutes=90))

    rows = get_daily_rows(db, DAY)
    assert len(rows) == 1
    assert rows[0].status == "Checked out"
    assert rows[0].duration_minutes == 90


def test_other_day_is_excluded(db, site):
    a = _student(db, site, "Aisha", "Middle School", "a@example.com")
    process_scan(db, a.id, "7382", now=MORNING)
    # Nothing on the day before.
    assert get_daily_summary(db, DAY - timedelta(days=1))["present"] == 0
