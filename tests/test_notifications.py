"""Tests for the parent notification layer (M5)."""
from datetime import datetime, timedelta

import pytest

from app import security
from app.models import Guardian, Site, Student
from app.notifications import build_email, payload_from_result, send_notification
from app.services import process_scan

NOW = datetime(2026, 8, 2, 16, 2, 0)


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, text, html=None):
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


@pytest.fixture()
def student(db):
    site = Site(name="Boston", active=True)
    db.add(site)
    db.flush()
    s = Student(
        first_name="Maya", last_name="Chen", active=True,
        pin_hash=security.hash_pin("7382"), site_id=site.id,
    )
    db.add(s)
    db.flush()
    db.add(Guardian(student_id=s.id, email="parent@example.com"))
    db.commit()
    return s


def test_check_in_produces_a_notification(db, student):
    result = process_scan(db, student.id, "7382", now=NOW)
    payload = payload_from_result(result)
    assert payload is not None
    assert payload.to_emails == ["parent@example.com"]
    assert payload.action == "checked in"

    sender = FakeSender()
    assert send_notification(payload, sender=sender) is True
    assert len(sender.sent) == 1
    assert "checked in" in sender.sent[0]["subject"]
    assert "Maya Chen" in sender.sent[0]["subject"]


def test_check_out_produces_a_notification(db, student):
    process_scan(db, student.id, "7382", now=NOW)
    result = process_scan(db, student.id, "7382", now=NOW + timedelta(hours=2))
    payload = payload_from_result(result)
    assert payload.action == "checked out"

    sender = FakeSender()
    send_notification(payload, sender=sender)
    assert "checked out" in sender.sent[0]["subject"]


def test_bad_pin_produces_no_notification(db, student):
    result = process_scan(db, student.id, "0000", now=NOW)
    assert payload_from_result(result) is None


def test_blocked_by_time_guard_produces_no_notification(db, student, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "time_guard_minutes", 30)
    process_scan(db, student.id, "7382", now=NOW)
    result = process_scan(db, student.id, "7382", now=NOW + timedelta(minutes=2))
    assert payload_from_result(result) is None


def test_missing_email_sends_nothing_but_does_not_error(db):
    site = Site(name="Boston", active=True)
    db.add(site)
    db.flush()
    s = Student(first_name="No", last_name="Email", active=True,
                pin_hash=security.hash_pin("7382"), site_id=site.id)
    db.add(s)
    db.flush()
    db.add(Guardian(student_id=s.id, email=None))
    db.commit()

    result = process_scan(db, s.id, "7382", now=NOW)
    payload = payload_from_result(result)
    sender = FakeSender()
    assert send_notification(payload, sender=sender) is False
    assert sender.sent == []


def test_multiple_guardians_all_receive(db, student):
    # Add a second guardian email to the same student.
    db.add(Guardian(student_id=student.id, email="second@example.com"))
    db.commit()

    result = process_scan(db, student.id, "7382", now=NOW)
    payload = payload_from_result(result)
    assert set(payload.to_emails) == {"parent@example.com", "second@example.com"}

    sender = FakeSender()
    send_notification(payload, sender=sender)
    assert len(sender.sent) == 1
    assert "parent@example.com" in sender.sent[0]["to"]
    assert "second@example.com" in sender.sent[0]["to"]


def test_email_content_has_name_site_and_time(db, student):
    result = process_scan(db, student.id, "7382", now=NOW)
    subject, text, html = build_email(payload_from_result(result))
    assert "Maya Chen" in text
    assert "Boston" in text
    assert "Maya Chen" in html
