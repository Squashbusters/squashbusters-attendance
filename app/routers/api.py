"""Kiosk JSON API (L2) — the thin layer the tablet UI calls."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Site, Student
from app.notifications import payload_from_result, send_notification
from app.services import process_scan

router = APIRouter(prefix="/api", tags=["kiosk"])


class StudentOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    full_name: str
    program: str | None = None


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


@router.get("/students", response_model=list[StudentOut])
def list_students(site_id: int | None = None, db: Session = Depends(get_db)):
    """Active students at a site, for the kiosk name picker."""
    site = _resolve_site(db, site_id)
    if site is None:
        return []
    students = (
        db.execute(
            select(Student)
            .where(Student.site_id == site.id, Student.active.is_(True))
            .order_by(Student.first_name, Student.last_name)
        )
        .scalars()
        .all()
    )
    return [
        StudentOut(
            id=s.id,
            first_name=s.first_name,
            last_name=s.last_name,
            full_name=s.full_name,
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
        background_tasks.add_task(send_notification, notif)

    return CheckInResponse(ok=result.ok, status=result.status.value, message=result.message)
