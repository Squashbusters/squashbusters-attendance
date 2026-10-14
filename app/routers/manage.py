"""Live editing of roster records (staff, behind login).

Edit a student's details, edit/add/remove their guardians, reset a lost PIN, or
delete a student entirely. Reached from the "Edit" button on each master-sheet
row. All routes are login-gated (same guard as the dashboard).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import security
from app.auth import require_login
from app.config import settings
from app.database import get_db
from app.models import Guardian, Student

router = APIRouter(tags=["manage"], dependencies=[Depends(require_login)])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

GRADES = [
    "5th Grade", "6th Grade", "7th Grade", "8th Grade",
    "9th Grade", "10th Grade", "11th Grade", "12th Grade",
]


def _get_student(db: Session, student_id: int) -> Student | None:
    return db.get(Student, student_id)


@router.get("/manage/student/{student_id}", response_class=HTMLResponse)
def edit_form(
    student_id: int,
    request: Request,
    db: Session = Depends(get_db),
    saved: int | None = None,
    error: str | None = None,
):
    student = _get_student(db, student_id)
    if student is None:
        return RedirectResponse("/dashboard/roster", status_code=303)
    # A freshly reset PIN is stashed in the session (never put in the URL/logs)
    # and shown exactly once.
    new_pin = request.session.pop(f"pin_{student_id}", None)
    return templates.TemplateResponse(
        "manage_student.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "student": student,
            "guardians": list(student.guardians),
            "grades": GRADES,
            "saved": saved,
            "new_pin": new_pin,
            "error": error,
        },
    )


@router.post("/manage/student/{student_id}")
async def update_student(
    student_id: int, request: Request, db: Session = Depends(get_db)
):
    student = _get_student(db, student_id)
    if student is None:
        return RedirectResponse("/dashboard/roster", status_code=303)
    form = await request.form()

    first = (form.get("first_name") or "").strip()
    last = (form.get("last_name") or "").strip()
    if not first or not last:
        return RedirectResponse(
            f"/manage/student/{student_id}?error=Student+first+and+last+name+are+required.",
            status_code=303,
        )

    student.first_name = first
    student.last_name = last
    student.grade = (form.get("grade") or "").strip() or None
    student.current_program_status = (form.get("status") or "").strip() or None
    student.email = (form.get("student_email") or "").strip() or None
    student.phone = (form.get("student_phone") or "").strip() or None

    # Guardian rows arrive as g-<i>-<field>. Existing rows carry g-<i>-id; new
    # rows (added in the browser) have a blank id. A row removed in the browser
    # simply isn't submitted, so any existing guardian whose id is absent from
    # the submission is deleted.
    indices = sorted(
        {int(m.group(1)) for k in form.keys() if (m := re.match(r"g-(\d+)-name$", k))}
    )
    existing = {g.id: g for g in student.guardians}
    kept_ids: set[int] = set()

    for i in indices:
        gid = (form.get(f"g-{i}-id") or "").strip()
        name = (form.get(f"g-{i}-name") or "").strip()
        rel = (form.get(f"g-{i}-relationship") or "").strip() or None
        email = (form.get(f"g-{i}-email") or "").strip() or None
        phone = (form.get(f"g-{i}-phone") or "").strip() or None

        if gid:
            g = existing.get(int(gid))
            if g is None:
                continue
            kept_ids.add(int(gid))
            if not (name or email or phone):
                db.delete(g)  # existing row cleared out -> remove it
                continue
            g.name = name or None
            g.relationship_type = rel
            g.email = email
            g.phone = phone
        elif name or email or phone:
            db.add(
                Guardian(
                    student_id=student.id,
                    name=name or None,
                    relationship_type=rel,
                    email=email,
                    phone=phone,
                )
            )

    for gid, g in existing.items():
        if gid not in kept_ids:
            db.delete(g)  # removed in the browser

    db.commit()
    return RedirectResponse(f"/manage/student/{student_id}?saved=1", status_code=303)


@router.post("/manage/student/{student_id}/reset-pin")
def reset_pin(student_id: int, request: Request, db: Session = Depends(get_db)):
    student = _get_student(db, student_id)
    if student is None:
        return RedirectResponse("/dashboard/roster", status_code=303)
    pin = security.generate_pin(security.existing_pins(db))
    student.pin_hash = security.hash_pin(pin)
    student.pin = pin
    db.commit()
    # Hand the new PIN to the edit page via the session (kept out of the URL).
    request.session[f"pin_{student_id}"] = pin
    # Return to the PIN panel when the reset was triggered from there.
    if request.query_params.get("next") == "pins":
        return RedirectResponse("/dashboard/pins", status_code=303)
    return RedirectResponse(f"/manage/student/{student_id}", status_code=303)


@router.post("/manage/student/{student_id}/status")
def set_status(student_id: int, status: str = Form(""), db: Session = Depends(get_db)):
    """Update a student's status inline from the Records table (Active / Trying
    Out / Inactive / blank)."""
    student = _get_student(db, student_id)
    if student is None:
        return {"ok": False}
    student.current_program_status = (status or "").strip() or None
    db.commit()
    return {"ok": True}


@router.post("/manage/student/{student_id}/reset-pin.json")
def reset_pin_json(student_id: int, db: Session = Depends(get_db)):
    """Regenerate a PIN and return it as JSON, so the PIN panel can update one
    row in place without reloading the whole page."""
    student = _get_student(db, student_id)
    if student is None:
        return {"ok": False}
    pin = security.generate_pin(security.existing_pins(db))
    student.pin_hash = security.hash_pin(pin)
    student.pin = pin
    db.commit()
    return {"ok": True, "pin": pin}


@router.post("/manage/student/{student_id}/delete")
def delete_student(student_id: int, db: Session = Depends(get_db)):
    student = _get_student(db, student_id)
    if student is not None:
        db.delete(student)  # cascades to guardians + attendance events
        db.commit()
    return RedirectResponse("/dashboard/roster", status_code=303)
