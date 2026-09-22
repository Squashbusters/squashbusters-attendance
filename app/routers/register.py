"""Open walk-in registration (public) — reachable from the kiosk and dashboard.

Anyone at the kiosk can add a student who isn't in the system yet and get a PIN.
Intentionally not login-gated (a stakeholder-requested "open" option); staff reach
the same form from the dashboard.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import security
from app.config import settings
from app.database import get_db
from app.importer import _get_or_create_program, _get_or_create_site
from app.models import Guardian, Student

router = APIRouter(tags=["register"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)

GRADES = [
    "5th Grade", "6th Grade", "7th Grade", "8th Grade",
    "9th Grade", "10th Grade", "11th Grade", "12th Grade",
]


def _guardian_from_form(
    na: str | None, name: str, email: str, phone: str, relationship: str
) -> Guardian | None:
    if na:
        return None
    name = (name or "").strip()
    if not name:
        return None
    return Guardian(
        name=name,
        relationship_type=relationship,
        email=(email or "").strip() or None,
        phone=(phone or "").strip() or None,
    )


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {"request": request, "app_name": settings.app_name, "grades": GRADES},
    )


@router.post("/register", response_class=HTMLResponse)
def register_student(
    request: Request,
    db: Session = Depends(get_db),
    first_name: str = Form(""),
    last_name: str = Form(""),
    grade: str = Form(""),
    student_email: str = Form(""),
    student_phone: str = Form(""),
    program: str = Form("E-HS Program"),
    site: str = Form("Boston"),
    mother_na: str | None = Form(None),
    mother_name: str = Form(""),
    mother_email: str = Form(""),
    mother_phone: str = Form(""),
    father_na: str | None = Form(None),
    father_name: str = Form(""),
    father_email: str = Form(""),
    father_phone: str = Form(""),
    other_relationship: str = Form(""),
    other_name: str = Form(""),
    other_email: str = Form(""),
    other_phone: str = Form(""),
):
    first_name = first_name.strip()
    last_name = last_name.strip()

    def render(**extra):
        ctx = {
            "request": request,
            "app_name": settings.app_name,
            "grades": GRADES,
            "form": {
                "first_name": first_name, "last_name": last_name, "grade": grade,
                "student_email": student_email, "student_phone": student_phone,
                "mother_na": mother_na, "mother_name": mother_name,
                "mother_email": mother_email, "mother_phone": mother_phone,
                "father_na": father_na, "father_name": father_name,
                "father_email": father_email, "father_phone": father_phone,
                "other_relationship": other_relationship, "other_name": other_name,
                "other_email": other_email, "other_phone": other_phone,
            },
        }
        ctx.update(extra)
        return templates.TemplateResponse("register.html", ctx)

    if not first_name or not last_name:
        return render(error="Student first and last name are required.")
    if grade not in GRADES:
        return render(error="Please choose the student's grade.")

    guardians = [
        g for g in (
            _guardian_from_form(mother_na, mother_name, mother_email, mother_phone, "Mother"),
            _guardian_from_form(father_na, father_name, father_email, father_phone, "Father"),
            _guardian_from_form(None, other_name, other_email, other_phone,
                                (other_relationship or "Other").strip() or "Other"),
        ) if g is not None
    ]
    if not guardians:
        return render(error="At least one guardian is required (mark absent parents N/A, or add an 'Other' guardian).")
    if not any(g.email or g.phone for g in guardians):
        return render(error="At least one guardian needs an email or phone so notifications can be sent.")

    the_site = _get_or_create_site(db, site)
    the_program = _get_or_create_program(db, program)
    pin = security.generate_pin()
    student = Student(
        first_name=first_name,
        last_name=last_name,
        grade=grade,
        email=student_email.strip() or None,
        phone=student_phone.strip() or None,
        active=True,
        pin_hash=security.hash_pin(pin),
        site_id=the_site.id,
        program_id=the_program.id if the_program else None,
    )
    for g in guardians:
        g.student = student
    db.add(student)
    db.add_all(guardians)
    db.commit()

    return render(created=True, new_pin=pin, new_name=f"{first_name} {last_name}", new_grade=grade)
