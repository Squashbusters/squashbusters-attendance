"""Closet station (L1) — the third student-facing surface, beside the kiosk.

A student loans or returns equipment with the SAME PIN they check in with.
This is the inventory module folded into the check-in app.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_kiosk_access
from app.config import settings
from app.database import get_db
from app.models import Item, Loan, Student

router = APIRouter(tags=["closet-ui"], dependencies=[Depends(require_kiosk_access)])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _open_loan(db: Session, item_id: int) -> Loan | None:
    return (
        db.query(Loan)
        .filter(Loan.item_id == item_id, Loan.status == "Out")
        .order_by(Loan.checked_out.desc())
        .first()
    )


def _available_by_type(db: Session) -> dict[str, list[dict]]:
    by_type: dict[str, list[dict]] = {}
    for it in db.query(Item).filter(Item.status == "Available").order_by(Item.code).all():
        by_type.setdefault(it.type, []).append({"code": it.code, "size": it.size or ""})
    return by_type


def _render(request, db, **extra):
    ctx = {
        "request": request, "app_name": settings.app_name,
        "by_type": _available_by_type(db),
        "msg": "", "err": "", "my_items": None, "return_pin": "", "show_return": False,
    }
    ctx.update(extra)
    return templates.TemplateResponse("closet.html", ctx)


@router.get("/closet", response_class=HTMLResponse)
def closet(request: Request, msg: str = "", err: str = "", db: Session = Depends(get_db)):
    return _render(request, db, msg=msg, err=err)


def _my_items(db: Session, student: Student) -> list[dict]:
    loans = db.query(Loan).filter(
        Loan.student_id == student.id, Loan.status == "Out"
    ).all()
    return [
        {"code": l.item.code, "type": l.item.type, "size": l.item.size or ""}
        for l in loans
    ]


@router.post("/closet")
def closet_action(
    request: Request,
    pin: str = Form(...),
    code: list[str] = Form(default=[]),
    mode: str = Form("loan"),
    db: Session = Depends(get_db),
):
    student = db.query(Student).filter(Student.pin == pin.strip()).first() if pin.strip() else None
    if not student:
        return _render(request, db, err="PIN not recognized.", show_return=(mode != "loan"))

    codes = [c.strip() for c in code if c.strip()]

    # Step 1 of returning: look up what this student currently has out.
    if mode == "return_lookup":
        my_items = _my_items(db, student)
        if not my_items:
            return _render(request, db, show_return=True,
                           err=f"{student.full_name}, you have nothing to return.")
        return _render(request, db, show_return=True, my_items=my_items,
                       return_pin=pin.strip())

    # Returning one or more selected items.
    if mode == "return":
        if not codes:
            return _render(request, db, show_return=True, my_items=_my_items(db, student),
                           return_pin=pin.strip(), err="Select at least one item to return.")
        returned = []
        for c in codes:
            item = db.query(Item).filter(Item.code.ilike(c)).first()
            if not item:
                continue
            ol = _open_loan(db, item.id)
            if ol and ol.student_id == student.id:
                ol.returned = datetime.utcnow()
                ol.status = "Returned"
                item.status = "Available"
                returned.append(item.code)
        db.commit()
        if not returned:
            return _render(request, db, show_return=True, my_items=_my_items(db, student),
                           return_pin=pin.strip(), err="Those aren't checked out to you.")
        joined = ", ".join(returned).replace(" ", "+")
        return RedirectResponse(
            f"/closet?msg={joined}+returned.+Thanks,+{student.full_name}!", status_code=303
        )

    # mode == "loan" (one or more items in a single trip)
    if not codes:
        return _render(request, db, err="Pick at least one item first.")
    loaned: list[str] = []
    for c in codes:
        item = db.query(Item).filter(Item.code.ilike(c)).first()
        if item is None or item.status != "Available":
            continue
        db.add(Loan(item_id=item.id, student_id=student.id, status="Out"))
        item.status = "Checked Out"
        loaned.append(item.code)
    db.commit()
    if not loaned:
        return RedirectResponse(
            "/closet?err=Sorry,+none+of+those+are+available+anymore.", status_code=303
        )
    joined = ", ".join(loaned).replace(" ", "+")
    return RedirectResponse(
        f"/closet?msg={joined}+loaned+to+{student.full_name}.", status_code=303
    )
