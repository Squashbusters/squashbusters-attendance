"""Tests for the roster CSV bulk-import (M1 verification)."""
from app import security
from app.importer import import_roster_csv
from app.models import Guardian, Student

HEADER = "first_name,last_name,program,site,guardian_email,pin\n"


def test_valid_import_hashes_pins(db):
    csv = HEADER + (
        "Maya,Chen,Middle School,Boston,parent@example.com,7382\n"
        "Devon,Ruiz,High School,Boston,other@example.com,4820\n"
    )
    result = import_roster_csv(db, csv)

    assert result.ok
    assert result.imported == 2
    students = db.query(Student).all()
    assert len(students) == 2
    # PIN is stored hashed, never in plaintext, and verifies correctly.
    maya = db.query(Student).filter_by(first_name="Maya").one()
    assert maya.pin_hash and maya.pin_hash != "7382"
    assert security.verify_pin("7382", maya.pin_hash)
    assert not security.verify_pin("0000", maya.pin_hash)


def test_bad_pin_is_a_hard_error_and_blocks_whole_file(db):
    csv = HEADER + (
        "Maya,Chen,Middle School,Boston,parent@example.com,7382\n"
        "Bad,Pin,High School,Boston,other@example.com,12\n"  # too short
    )
    result = import_roster_csv(db, csv)

    assert not result.ok
    assert result.imported == 0
    # all-or-nothing: the good row is not committed either
    assert db.query(Student).count() == 0
    assert any("digits" in e.message for e in result.errors)


def test_weak_pin_rejected(db):
    csv = HEADER + "Weak,Pin,Middle School,Boston,parent@example.com,1234\n"
    result = import_roster_csv(db, csv)
    assert not result.ok
    assert any("guess" in e.message for e in result.errors)


def test_duplicate_name_same_site_rejected(db):
    csv = HEADER + (
        "Maya,Chen,Middle School,Boston,a@example.com,7382\n"
        "Maya,Chen,High School,Boston,b@example.com,4820\n"
    )
    result = import_roster_csv(db, csv)
    assert not result.ok
    assert any("Duplicate" in e.message for e in result.errors)


def test_missing_email_is_warning_not_error(db):
    csv = HEADER + "Maya,Chen,Middle School,Boston,,7382\n"
    result = import_roster_csv(db, csv)

    assert result.ok
    assert result.imported == 1
    assert any("no guardian email" in w.message for w in result.warnings)
    # A row with no guardian details at all creates no (empty) guardian rows.
    assert db.query(Guardian).count() == 0


def test_invalid_email_flagged_and_not_persisted(db):
    csv = HEADER + "Maya,Chen,Middle School,Boston,not-an-email,7382\n"
    result = import_roster_csv(db, csv)

    assert result.ok
    assert any("invalid guardian email" in w.message for w in result.warnings)
    assert db.query(Guardian).one().email is None


def test_missing_column_is_rejected(db):
    csv = "first_name,last_name,site,pin\nMaya,Chen,Boston,7382\n"
    result = import_roster_csv(db, csv)
    assert not result.ok
    assert any("Missing required column" in e.message for e in result.errors)
