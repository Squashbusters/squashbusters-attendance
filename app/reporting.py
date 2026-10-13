"""Reporting queries (L4 reads feeding the L1 dashboard & daily report)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AttendanceEvent, Guardian, Program, Site, Student


@dataclass
class DailyRow:
    student_name: str
    grade: str | None
    program: str | None
    site: str
    check_in: datetime
    check_out: datetime | None
    guardian_email: str | None
    check_in_photo: str | None = None
    check_out_photo: str | None = None

    @property
    def status(self) -> str:
        return "Checked out" if self.check_out else "Still in"

    @property
    def duration_minutes(self) -> int | None:
        if not self.check_out:
            return None
        return int((self.check_out - self.check_in).total_seconds() // 60)

    @property
    def has_email(self) -> bool:
        return bool(self.guardian_email)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)
    return start, end


def get_daily_rows(db: Session, day: date, site_id: int | None = None) -> list[DailyRow]:
    """Every check-in event for the day — the raw material of the daily report."""
    start, end = _day_bounds(day)
    stmt = (
        select(AttendanceEvent, Student, Program, Site)
        .join(Student, AttendanceEvent.student_id == Student.id)
        .join(Site, AttendanceEvent.site_id == Site.id)
        .outerjoin(Program, Student.program_id == Program.id)
        .where(AttendanceEvent.check_in_at >= start, AttendanceEvent.check_in_at <= end)
        .order_by(AttendanceEvent.check_in_at)
    )
    if site_id is not None:
        stmt = stmt.where(AttendanceEvent.site_id == site_id)

    rows: list[DailyRow] = []
    for event, student, program, site in db.execute(stmt).all():
        guardian = student.guardians[0].email if student.guardians else None
        rows.append(
            DailyRow(
                student_name=student.full_name,
                grade=student.grade,
                program=program.name if program else None,
                site=site.name,
                check_in=event.check_in_at,
                check_out=event.check_out_at,
                guardian_email=guardian,
                check_in_photo=event.check_in_photo,
                check_out_photo=event.check_out_photo,
            )
        )
    return rows


def _grade_sort_key(grade: str) -> tuple[int, str]:
    """Order grades numerically ('6th' before '12th'); unknown/blank last."""
    import re

    m = re.match(r"\s*(\d+)", grade or "")
    return (int(m.group(1)) if m else 99, grade or "")


def get_daily_summary(db: Session, day: date, site_id: int | None = None) -> dict:
    """Headline metrics for the dashboard (all live off the day's check-ins)."""
    rows = get_daily_rows(db, day, site_id)

    present = len(rows)
    still_in = sum(1 for r in rows if r.check_out is None)
    checked_out = present - still_in
    missing_email = sum(1 for r in rows if not r.has_email)

    # Present count grouped by grade (the meaningful dimension now).
    grade_counts: dict[str, int] = {}
    for r in rows:
        key = r.grade or "Other"
        grade_counts[key] = grade_counts.get(key, 0) + 1
    by_grade = {g: grade_counts[g] for g in sorted(grade_counts, key=_grade_sort_key)}

    # Who's in the building right now (open check-ins), earliest first.
    checked_in = [
        {
            "name": r.student_name,
            "grade": r.grade or "—",
            "since": r.check_in.strftime("%-I:%M %p"),
        }
        for r in rows
        if r.check_out is None
    ]

    # Roster size for an attendance-rate denominator.
    total_stmt = select(func.count(Student.id)).where(Student.active.is_(True))
    if site_id is not None:
        total_stmt = total_stmt.where(Student.site_id == site_id)
    total_active = db.execute(total_stmt).scalar_one()

    return {
        "date": day.isoformat(),
        "present": present,
        "still_in": still_in,
        "checked_out": checked_out,
        "missing_email": missing_email,
        "total_active": total_active,
        "attendance_rate": round(100 * present / total_active) if total_active else 0,
        "by_grade": by_grade,
        "checked_in": checked_in,
    }


def _guardian_slot(guardians: list[Guardian], kinds: set[str]) -> Guardian | None:
    for g in guardians:
        if (g.relationship_type or "") in kinds:
            return g
    return None


def get_roster(db: Session, site_id: int | None = None) -> list[dict]:
    """The full 'master sheet' — every active student with flattened guardians."""
    stmt = select(Student).where(Student.active.is_(True))
    if site_id is not None:
        stmt = stmt.where(Student.site_id == site_id)
    students = db.execute(stmt).scalars().all()
    students.sort(key=lambda s: (_grade_sort_key(s.grade or ""), s.last_name.lower(), s.first_name.lower()))

    MOTHER, FATHER = {"Mother", "Stepmother"}, {"Father", "Stepfather"}
    rows: list[dict] = []
    for s in students:
        gs = list(s.guardians)
        mom = _guardian_slot(gs, MOTHER)
        dad = _guardian_slot(gs, FATHER)
        others = [g for g in gs if g not in (mom, dad)]
        other_txt = "; ".join(
            f"{g.name} ({g.relationship_type or 'Other'})" for g in others if g.name
        )
        rows.append({
            "id": s.id,
            "name": s.full_name,
            "grade": s.grade or "",
            "pin": s.pin or "",
            "current_program_status": s.current_program_status or "",
            "contact_record_type": s.contact_record_type or "",
            "program_engagement_name": s.program_engagement_name or "",
            "contact_id": s.contact_id or "",
            "site": s.site.name if s.site else "",
            "program": s.program.name if s.program else "",
            "student_email": s.email or "",
            "student_phone": s.phone or "",
            "mother_name": mom.name if mom else "",
            "mother_email": (mom.email if mom else "") or "",
            "mother_phone": (mom.phone if mom else "") or "",
            "father_name": dad.name if dad else "",
            "father_email": (dad.email if dad else "") or "",
            "father_phone": (dad.phone if dad else "") or "",
            "other_guardians": other_txt,
            "added": s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
        })
    return rows


def get_recently_added(db: Session, limit: int = 10) -> list[dict]:
    """Most recently registered students added through the system (walk-in
    registrations). Bulk-imported roster students carry a Salesforce
    contact_id; walk-ins do not, so filter to contact_id IS NULL."""
    stmt = (
        select(Student)
        .where(
            Student.active.is_(True),
            Student.created_at.is_not(None),
            Student.contact_id.is_(None),
        )
        .order_by(Student.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "name": s.full_name,
            "grade": s.grade or "—",
            "added": s.created_at.strftime("%b %-d, %-I:%M %p") if s.created_at else "",
        }
        for s in db.execute(stmt).scalars().all()
    ]


def get_attendance_trend(
    db: Session, end_day: date, days: int = 7, site_id: int | None = None
) -> list[dict]:
    """Present-count per day for the `days` ending at `end_day` (for a trend line)."""
    out: list[dict] = []
    for i in range(days - 1, -1, -1):
        d = end_day - timedelta(days=i)
        present = len(get_daily_rows(db, d, site_id))
        out.append({"date": d.isoformat(), "label": d.strftime("%a %-m/%-d"), "present": present})
    return out


def get_missing_contact(db: Session, site_id: int | None = None) -> list[dict]:
    """Active students with NO guardian email on file (so they receive no
    notifications). Flags whether a guardian phone exists as a fallback."""
    stmt = select(Student).where(Student.active.is_(True))
    if site_id is not None:
        stmt = stmt.where(Student.site_id == site_id)
    rows: list[dict] = []
    for s in db.execute(stmt).scalars().all():
        if any(g.email for g in s.guardians):
            continue  # has at least one guardian email -> not missing
        phones = [g.phone for g in s.guardians if g.phone]
        names = [g.name for g in s.guardians if g.name]
        rows.append({
            "id": s.id,
            "name": s.full_name,
            "grade": s.grade or "—",
            "site": s.site.name if s.site else "",
            "guardians": ", ".join(names) if names else "(none on file)",
            "has_phone": bool(phones),
            "phone": phones[0] if phones else "",
        })
    rows.sort(key=lambda r: (_grade_sort_key(r["grade"]), r["name"].lower()))
    return rows
