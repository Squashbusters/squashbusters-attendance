"""Kiosk JSON API (L2) — the thin layer the tablet UI calls."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Site, Student
from app.notifications import payload_from_result, send_notification, send_sms_notification
from app.services import process_scan

router = APIRouter(prefix="/api", tags=["kiosk"])


class StudentOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    grade: str | None = None
    program: str | None = None


class GradeOut(BaseModel):
    grade: str
    count: int


def _grade_sort_key(grade: str) -> tuple[int, str]:
    """Order grades numerically ('6th Grade' before '12th Grade'); unknown last."""
    import re

    m = re.match(r"\s*(\d+)", grade or "")
    return (int(m.group(1)) if m else 99, grade or "")


class CheckInRequest(BaseModel):
    student_id: int
    pin: str = Field(min_length=1, max_length=12)
    photo: str | None = None  # base64 data-URL from the kiosk camera


class CheckInResponse(BaseModel):
    ok: bool
    status: str
    message: str


def _resolve_site(db: Session, site_id: int | None) -> Site | None:
    if site_id is not None:
        return db.get(Site, site_id)
    # Default to the first active site (single-site launch = Boston).
    return db.execute(
        select(Site).where(Site.active.is_(True)).order_by(Site.id)
    ).scalars().first()


@router.get("/grades", response_model=list[GradeOut])
def list_grades(site_id: int | None = None, db: Session = Depends(get_db)):
    """Grades for the kiosk landing screen.

    Always returns the configured canonical grades (``settings.kiosk_grade_list``,
    e.g. 5th–12th) so the board is consistent even when a grade has no students
    yet. Any grade found on students but outside that list (including students
    with no grade, shown as "Other") is appended so nobody is unreachable.
    """
    site = _resolve_site(db, site_id)
    if site is None:
        return []
    students = (
        db.execute(
            select(Student).where(Student.site_id == site.id, Student.active.is_(True))
        )
        .scalars()
        .all()
    )
    counts: dict[str, int] = {}
    for s in students:
        label = s.grade or "Other"
        counts[label] = counts.get(label, 0) + 1

    canonical = settings.kiosk_grade_list
    out = [GradeOut(grade=g, count=counts.get(g, 0)) for g in canonical]
    extras = sorted(
        (g for g in counts if g not in canonical), key=_grade_sort_key
    )
    out.extend(GradeOut(grade=g, count=counts[g]) for g in extras)
    return out


@router.get("/students", response_model=list[StudentOut])
def list_students(
    site_id: int | None = None,
    grade: str | None = None,
    db: Session = Depends(get_db),
):
    """Active students at a site, for the kiosk name picker.

    When ``grade`` is given, only students in that grade are returned (the kiosk
    calls this after a grade is tapped). ``grade=Other`` matches students with no
    grade on file, mirroring the label used by ``/grades``.
    """
    site = _resolve_site(db, site_id)
    if site is None:
        return []
    stmt = (
        select(Student)
        .where(Student.site_id == site.id, Student.active.is_(True))
        .order_by(Student.first_name, Student.last_name)
    )
    if grade is not None:
        if grade == "Other":
            stmt = stmt.where(Student.grade.is_(None))
        else:
            stmt = stmt.where(Student.grade == grade)
    students = db.execute(stmt).scalars().all()
    return [
        StudentOut(
            id=s.id,
            first_name=s.first_name,
            last_name=s.last_name,
            full_name=s.full_name,
            grade=s.grade,
            program=s.program.name if s.program else None,
        )
        for s in students
    ]


@router.post("/checkin", response_model=CheckInResponse)
def checkin(
    payload: CheckInRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Single endpoint — the server decides check-in vs check-out.

    On a successful check-in/out, the parent notification is queued as a
    background task so a slow email never delays the kiosk response.
    """
    result = process_scan(db, payload.student_id, payload.pin, photo=payload.photo)

    notif = payload_from_result(result)
    if notif is not None:
        background_tasks.add_task(send_notification, notif)      # email
        background_tasks.add_task(send_sms_notification, notif)  # SMS (no-op unless enabled)

    return CheckInResponse(ok=result.ok, status=result.status.value, message=result.message)
