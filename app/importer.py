"""CSV roster bulk-import (Admin feature in L1, writing to L4).

Expected columns (header row, case-insensitive):
    first_name, last_name, program, site, guardian_email, pin
Optional columns:
    grade                (e.g. "6th Grade"; groups the kiosk name picker)
    student_email, student_phone   (the student's own contact details)
    guardian_phone       (guardian mobile; used for the optional SMS channel)
    Multiple guardians, any one convention:
      * guardian1_name/relationship/email/phone, guardian2_* ...
      * mother_name/email/phone, father_*, other_relationship/other_name/email/phone
    contact_id, current_program_status, contact_record_type,
    program_engagement_name        (Salesforce reference fields for the master sheet)

Rules:
  * Missing first/last name        -> row skipped (error)
  * Bad PIN format / weak PIN       -> row skipped (error)
  * Duplicate name within same site -> row skipped (error, ambiguous at kiosk)
  * Missing / invalid guardian email-> row still imported, but flagged (warning)
PINs are hashed on import; the raw PIN is never persisted.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import security
from app.models import Guardian, Program, Site, Student

REQUIRED_COLUMNS = {"first_name", "last_name", "program", "site", "guardian_email", "pin"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class RowIssue:
    line: int
    message: str


@dataclass
class ImportResult:
    imported: int = 0
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[RowIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [{"line": i.line, "message": i.message} for i in self.errors],
            "warnings": [{"line": i.line, "message": i.message} for i in self.warnings],
        }


def _valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def _get_or_create_site(db: Session, name: str) -> Site:
    site = db.query(Site).filter(Site.name == name).first()
    if site is None:
        site = Site(name=name, active=True)
        db.add(site)
        db.flush()  # assign id without committing
    return site


def _get_or_create_program(db: Session, name: str) -> Program | None:
    if not name:
        return None
    program = db.query(Program).filter(Program.name == name).first()
    if program is None:
        program = Program(name=name)
        db.add(program)
        db.flush()
    return program


def _mk_guardian(name: str, relationship: str, email: str, phone: str) -> Guardian | None:
    """Build a Guardian from raw cell values, or None if the slot is empty."""
    name, relationship = (name or "").strip(), (relationship or "").strip()
    email, phone = (email or "").strip(), (phone or "").strip()
    if not (name or email or phone):
        return None
    return Guardian(
        name=name or None,
        relationship_type=relationship or None,
        email=email or None,
        phone=phone or None,
    )


def _build_guardians(row: dict) -> list[Guardian]:
    """Extract every guardian from a row, supporting three column conventions.

    Priority: guardian1_*/guardian2_*  ->  mother_/father_/other_  ->  the single
    guardian_email/guardian_phone (backward-compatible with old rosters).
    """
    # Convention A: guardian1_* / guardian2_*
    guardians: list[Guardian] = []
    for slot in ("guardian1", "guardian2"):
        g = _mk_guardian(
            row.get(f"{slot}_name", ""), row.get(f"{slot}_relationship", ""),
            row.get(f"{slot}_email", ""), row.get(f"{slot}_phone", ""),
        )
        if g:
            guardians.append(g)
    if guardians:
        return guardians

    # Convention B: mother_ / father_ / other_
    for name_key, rel in (("mother", "Mother"), ("father", "Father")):
        g = _mk_guardian(
            row.get(f"{name_key}_name", ""), rel,
            row.get(f"{name_key}_email", ""), row.get(f"{name_key}_phone", ""),
        )
        if g:
            guardians.append(g)
    other = _mk_guardian(
        row.get("other_name", ""), row.get("other_relationship", "") or "Other",
        row.get("other_email", ""), row.get("other_phone", ""),
    )
    if other:
        guardians.append(other)
    if guardians:
        return guardians

    # Legacy: single guardian_email / guardian_phone
    g = _mk_guardian(
        row.get("guardian_name", ""), row.get("guardian_relationship", ""),
        row.get("guardian_email", ""), row.get("guardian_phone", ""),
    )
    if g:
        guardians.append(g)
    return guardians


def import_roster_csv(db: Session, raw: str | bytes) -> ImportResult:
    """Parse and import a roster CSV. Commits only if there are no hard errors."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports

    result = ImportResult()
    reader = csv.DictReader(io.StringIO(raw))

    if reader.fieldnames is None:
        result.errors.append(RowIssue(0, "File is empty."))
        return result

    headers = {h.strip().lower() for h in reader.fieldnames}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        result.errors.append(
            RowIssue(0, f"Missing required column(s): {', '.join(sorted(missing))}")
        )
        return result

    # Track (site, full_name) within this file to catch in-file duplicates too.
    seen: set[tuple[str, str]] = set()
    staged: list[tuple[Student, list[Guardian]]] = []

    for offset, row in enumerate(reader):
        line = offset + 2  # +1 for header, +1 for 1-based counting
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}

        first = row.get("first_name", "")
        last = row.get("last_name", "")
        site_name = row.get("site", "")
        program_name = row.get("program", "")
        grade = row.get("grade", "")
        email = row.get("guardian_email", "")
        phone = row.get("guardian_phone", "")
        pin = row.get("pin", "")
        # Optional Salesforce reference fields (carried into the master sheet).
        contact_id = row.get("contact_id", "")
        current_program_status = row.get("current_program_status", "")
        contact_record_type = row.get("contact_record_type", "")
        program_engagement_name = row.get("program_engagement_name", "")
        student_email = row.get("student_email", "")
        student_phone = row.get("student_phone", "")

        if not first or not last:
            result.errors.append(RowIssue(line, "Missing first_name or last_name."))
            continue
        if not site_name:
            result.errors.append(RowIssue(line, "Missing site."))
            continue

        key = (site_name.lower(), f"{first} {last}".lower())
        if key in seen:
            result.errors.append(
                RowIssue(line, f"Duplicate name '{first} {last}' at site '{site_name}'.")
            )
            continue
        # Also guard against a name already in the DB at this site.
        exists = (
            db.query(Student)
            .join(Site)
            .filter(
                Site.name == site_name,
                Student.first_name == first,
                Student.last_name == last,
            )
            .first()
        )
        if exists:
            result.errors.append(
                RowIssue(line, f"'{first} {last}' already exists at site '{site_name}'.")
            )
            continue

        if not pin:
            result.errors.append(RowIssue(line, "Missing PIN."))
            continue
        if not security.is_valid_pin_format(pin):
            result.errors.append(RowIssue(line, f"PIN must be exactly {security.settings.pin_length} digits."))
            continue
        if security.is_weak_pin(pin):
            result.errors.append(RowIssue(line, "PIN is too easy to guess (e.g. 0000 / 1234)."))
            continue

        guardians = _build_guardians(row)
        for g in guardians:  # clear malformed emails, keep the guardian
            if g.email and not _valid_email(g.email):
                result.warnings.append(
                    RowIssue(line, f"'{first} {last}' has an invalid guardian email '{g.email}' — cleared.")
                )
                g.email = None
        if not any(g.email for g in guardians):
            result.warnings.append(
                RowIssue(line, f"'{first} {last}' has no guardian email — no email notifications will be sent.")
            )

        seen.add(key)
        site = _get_or_create_site(db, site_name)
        program = _get_or_create_program(db, program_name)
        student = Student(
            first_name=first,
            last_name=last,
            grade=grade or None,
            email=student_email or None,
            phone=student_phone or None,
            contact_id=contact_id or None,
            current_program_status=current_program_status or None,
            contact_record_type=contact_record_type or None,
            program_engagement_name=program_engagement_name or None,
            active=True,
            pin_hash=security.hash_pin(pin),
            site_id=site.id,
            program_id=program.id if program else None,
        )
        for g in guardians:
            g.student = student
        staged.append((student, guardians))

    if result.errors:
        db.rollback()  # all-or-nothing: don't import a partially-bad file
        result.imported = 0
        return result

    for student, guardians in staged:
        db.add(student)
        db.add_all(guardians)
    db.commit()
    result.imported = len(staged)
    return result
