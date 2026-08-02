"""Reporting queries (L4 reads feeding the L1 dashboard & daily report)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceEvent, Program, Site, Student


@dataclass
class DailyRow:
    student_name: str
    program: str | None
    site: str
    check_in: datetime
    check_out: datetime | None
    guardian_email: str | None

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
                program=program.name if program else None,
                site=site.name,
                check_in=event.check_in_at,
                check_out=event.check_out_at,
                guardian_email=guardian,
            )
        )
    return rows


def get_daily_summary(db: Session, day: date, site_id: int | None = None) -> dict:
    """Headline metrics for the dashboard."""
    rows = get_daily_rows(db, day, site_id)

    present = len(rows)
    still_in = sum(1 for r in rows if r.check_out is None)
    checked_out = present - still_in
    missing_email = sum(1 for r in rows if not r.has_email)

    by_program: dict[str, int] = {}
    for r in rows:
        key = r.program or "Unassigned"
        by_program[key] = by_program.get(key, 0) + 1

    return {
        "date": day.isoformat(),
        "present": present,
        "still_in": still_in,
        "checked_out": checked_out,
        "missing_email": missing_email,
        "by_program": by_program,
    }
