"""Dashboard & daily verification report (L1 for staff/leadership).

Auth is not wired yet (staff/admin login is the cross-cutting milestone). These
views are read-only reporting over the attendance data.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from app.auth import require_login
from app.clock import local_today
from app.config import settings
from app.database import get_db
from app.notifications import (
    payload_from_result,
    send_notification,
    send_sms_notification,
)
from app.reporting import (
    get_attendance_trend,
    get_daily_rows,
    get_daily_summary,
    get_missing_contact,
    get_recently_added,
    get_roster,
)
from app.services import process_scan
from app.auto_checkout import run_auto_checkout
from app.models import Item, Loan

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_login)])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _parse_day(day: str | None) -> date:
    if not day:
        return local_today()
    try:
        return date.fromisoformat(day)
    except ValueError:
        return local_today()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    day: str | None = None,
    msg: str | None = None,
    ok: str | None = None,
    db: Session = Depends(get_db),
):
    the_day = _parse_day(day)
    summary = get_daily_summary(db, the_day)
    # Lightweight list for the manual check-in picker (active students only).
    students = [
        {"id": r["id"], "name": r["name"], "grade": r["grade"]}
        for r in get_roster(db)
    ]
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "summary": summary,
            "day": the_day.isoformat(),
            "students": students,
            "flash": msg,
            "flash_ok": (ok != "0") if msg else None,
        },
    )


@router.post("/dashboard/scan")
def dashboard_scan(
    request: Request,
    background_tasks: BackgroundTasks,
    student_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Staff-side manual check-in/out from the dashboard.

    No PIN needed (the staff member is already signed in) and the double-tap
    guard is bypassed, so a correction right after a kiosk scan isn't blocked.
    Fires the same guardian notification as a kiosk scan.
    """
    result = process_scan(db, student_id, pin="", require_pin=False, guard_minutes=0)

    notif = payload_from_result(result)
    if notif is not None:
        background_tasks.add_task(send_notification, notif)
        background_tasks.add_task(send_sms_notification, notif)

    ok_flag = "1" if result.ok else "0"
    return RedirectResponse(
        url=f"/dashboard?msg={quote(result.message)}&ok={ok_flag}",
        status_code=303,
    )


@router.post("/dashboard/checkout-all")
def checkout_all(db: Session = Depends(get_db)):
    """End-of-day sweep: check out everyone still checked in. Staff-only (this
    router is behind require_login). Silent — no guardian notifications."""
    closed = run_auto_checkout(db)
    n = len(closed)
    note = (
        f"Checked out {n} student{'s' if n != 1 else ''}."
        if n else "Nobody was checked in."
    )
    return RedirectResponse(f"/dashboard?msg={quote(note)}&ok=1", status_code=303)


@router.get("/dashboard/roster", response_class=HTMLResponse)
def roster(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "roster.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "roster": get_roster(db),
            "recently_added": get_recently_added(db),
        },
    )


@router.get("/dashboard/pins", response_class=HTMLResponse)
def pins_panel(request: Request, db: Session = Depends(get_db)):
    """One screen listing every student so staff can reset a PIN in real time.
    The reset itself reuses the existing /manage/student/{id}/reset-pin flow,
    which generates a new PIN and shows it once (PINs stay hashed at rest)."""
    students = sorted(get_roster(db), key=lambda s: (s["grade"], s["name"]))
    return templates.TemplateResponse(
        "pins.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "students": students,
        },
    )


@router.get("/dashboard/pins.csv")
def pins_csv(db: Session = Depends(get_db)):
    """Download the student PIN list as CSV (staff-only)."""
    rows = sorted(get_roster(db), key=lambda s: (s["grade"], s["name"]))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student", "Grade", "Status", "PIN"])
    for r in rows:
        w.writerow([r["name"], r["grade"], r["status"], r["pin"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sqb_pins.csv"},
    )


@router.get("/dashboard/roster.csv")
def roster_csv(db: Session = Depends(get_db)):
    """Download the full records sheet as CSV (staff-only)."""
    rows = get_roster(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Name", "Grade", "Status", "Site", "PIN", "Student email", "Student phone",
                "Mother", "Mother email", "Mother phone",
                "Father", "Father email", "Father phone", "Other guardians"])
    for r in rows:
        w.writerow([r["name"], r["grade"], r["status"], r["site"], r["pin"],
                    r["student_email"], r["student_phone"],
                    r["mother_name"], r["mother_email"], r["mother_phone"],
                    r["father_name"], r["father_email"], r["father_phone"],
                    r["other_guardians"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sqb_records.csv"},
    )


@router.get("/dashboard/equipment", response_class=HTMLResponse)
def equipment_panel(request: Request, msg: str | None = None,
                    db: Session = Depends(get_db)):
    """Staff view of the closet: every item and who is holding it right now."""
    items = db.query(Item).order_by(Item.type, Item.code).all()
    open_loans = {
        l.item_id: l for l in db.query(Loan).filter(Loan.status == "Out").all()
    }
    rows = []
    by_type: dict[str, dict] = {}
    for it in items:
        ol = open_loans.get(it.id)
        is_out = ol is not None
        rows.append({
            "id": it.id, "code": it.code, "type": it.type, "size": it.size,
            "status": it.status, "condition": it.condition,
            "holder": ol.student.full_name if ol else None,
            "since": ol.checked_out.strftime("%m-%d-%Y") if ol and ol.checked_out else None,
        })
        bt = by_type.setdefault(it.type, {"type": it.type, "total": 0, "out": 0})
        bt["total"] += 1
        if is_out:
            bt["out"] += 1
    for bt in by_type.values():
        bt["available"] = bt["total"] - bt["out"]
    out = sum(1 for r in rows if r["holder"])
    total = len(rows)
    return templates.TemplateResponse(
        "equipment.html",
        {"request": request, "app_name": settings.app_name, "items": rows,
         "total": total, "out": out, "available": total - out,
         "conditions": ["Good", "Fair", "Needs Repair", "Retired"],
         "types": sorted(by_type.keys()),
         "flash": msg,
         "by_type": sorted(by_type.values(), key=lambda b: b["type"])},
    )


def _highest_code_num(db: Session, prefix: str) -> int:
    """Highest existing number for a code prefix (e.g. 5 for an existing R-005),
    or 0 if none exist yet."""
    highest = 0
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for (code,) in db.query(Item.code).filter(Item.code.like(f"{prefix}-%")).all():
        m = pat.match(code or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


@router.post("/dashboard/equipment/add")
def equipment_add(
    itype: list[str] = Form(default=[]),
    isize: list[str] = Form(default=[]),
    iqty: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Add inventory from the dashboard — several lines at once. Each line is a
    type + optional size + quantity; codes (e.g. C-001) are auto-generated and
    continue after whatever already exists for that type's prefix.

    A running per-prefix counter is kept across lines so that two lines sharing a
    prefix (e.g. two Shoes lines, S-) keep getting fresh codes instead of both
    starting from the same database number and colliding."""
    created = 0
    counters: dict[str, int] = {}
    # Pad the parallel lists so a row missing a trailing field still lines up.
    n_rows = max(len(itype), len(isize), len(iqty))
    def at(lst, i):
        return lst[i] if i < len(lst) else ""
    for i in range(n_rows):
        t = (at(itype, i) or "").strip()
        if not t:
            continue
        size = (at(isize, i) or "").strip() or None
        try:
            qty = int(at(iqty, i) or 0)
        except ValueError:
            qty = 0
        qty = max(0, min(qty, 300))  # sane cap
        if qty < 1:
            continue
        prefix = next((ch for ch in t.upper() if ch.isalnum()), "X")
        if prefix not in counters:
            counters[prefix] = _highest_code_num(db, prefix)
        for _ in range(qty):
            counters[prefix] += 1
            db.add(Item(code=f"{prefix}-{counters[prefix]:03d}", type=t, size=size,
                        status="Available", condition="Good"))
            created += 1
    db.commit()
    note = f"Added {created} item{'s' if created != 1 else ''}." if created else "Nothing to add."
    return RedirectResponse(f"/dashboard/equipment?msg={quote(note)}", status_code=303)


@router.post("/dashboard/equipment/{item_id}/delete")
def equipment_delete(item_id: int, db: Session = Depends(get_db)):
    """Remove an item from inventory. Blocked while it is checked out (return it
    first); returned-loan history for the item is removed with it."""
    item = db.get(Item, item_id)
    if item is not None:
        open_loan = db.query(Loan).filter(
            Loan.item_id == item_id, Loan.status == "Out"
        ).first()
        if open_loan is not None:
            return RedirectResponse(
                f"/dashboard/equipment?msg={quote(item.code + ' is checked out — return it before deleting.')}",
                status_code=303,
            )
        code = item.code
        db.delete(item)
        db.commit()
        return RedirectResponse(
            f"/dashboard/equipment?msg={quote('Deleted ' + code + '.')}",
            status_code=303,
        )
    return RedirectResponse("/dashboard/equipment", status_code=303)


@router.post("/dashboard/equipment/{item_id}/return")
def equipment_return(item_id: int, condition: str = Form("Good"),
                     db: Session = Depends(get_db)):
    """Staff-side return: mark the open loan returned and set the item's condition.
    A 'Needs Repair' item goes to In Repair instead of Available."""
    item = db.get(Item, item_id)
    if item is not None:
        loan = db.query(Loan).filter(
            Loan.item_id == item_id, Loan.status == "Out"
        ).first()
        if loan is not None:
            loan.returned = datetime.utcnow()
            loan.status = "Returned"
        if condition:
            item.condition = condition
        item.status = "In Repair" if condition == "Needs Repair" else "Available"
        db.commit()
    return RedirectResponse("/dashboard/equipment", status_code=303)


@router.post("/dashboard/equipment/{item_id}/condition")
def equipment_condition(item_id: int, condition: str = Form(...),
                        db: Session = Depends(get_db)):
    """Staff-side: update an item's condition without returning it."""
    item = db.get(Item, item_id)
    if item is not None and condition:
        item.condition = condition
        if item.status == "In Repair" and condition != "Needs Repair":
            item.status = "Available"
        elif condition == "Needs Repair" and item.status == "Available":
            item.status = "In Repair"
        db.commit()
    return RedirectResponse("/dashboard/equipment", status_code=303)


@router.get("/report/missing", response_class=HTMLResponse)
def missing_contact_report(request: Request, db: Session = Depends(get_db)):
    """Active students with no guardian email (they receive no notifications)."""
    rows = get_missing_contact(db)
    return templates.TemplateResponse(
        "missing_contact.html",
        {"request": request, "app_name": settings.app_name, "rows": rows},
    )


@router.get("/report/missing.csv")
def missing_contact_csv(db: Session = Depends(get_db)):
    rows = get_missing_contact(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student", "Grade", "Site", "Guardians on file", "Has phone", "Phone"])
    for r in rows:
        w.writerow([r["name"], r["grade"], r["site"], r["guardians"],
                    "Yes" if r["has_phone"] else "No", r["phone"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=missing_contact.csv"},
    )


@router.get("/api/dashboard/summary")
def dashboard_summary(day: str | None = None, site_id: int | None = None, db: Session = Depends(get_db)):
    return get_daily_summary(db, _parse_day(day), site_id)


@router.get("/api/dashboard/trend")
def dashboard_trend(
    day: str | None = None, days: int = 7, site_id: int | None = None, db: Session = Depends(get_db)
):
    return get_attendance_trend(db, _parse_day(day), days, site_id)


@router.get("/report/daily", response_class=HTMLResponse)
def daily_report(request: Request, day: str | None = None, db: Session = Depends(get_db)):
    the_day = _parse_day(day)
    rows = get_daily_rows(db, the_day)
    summary = get_daily_summary(db, the_day)
    return templates.TemplateResponse(
        "daily_report.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "rows": rows,
            "summary": summary,
            "day": the_day.isoformat(),
            "day_us": the_day.strftime("%m-%d-%Y"),
        },
    )


@router.get("/photos/{name}")
def photo(name: str):
    """Serve a check-in photo (staff-only via the router's login guard)."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid file")
    path = Path("photos") / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


@router.get("/report/daily.csv")
def daily_report_csv(day: str | None = None, db: Session = Depends(get_db)):
    the_day = _parse_day(day)
    rows = get_daily_rows(db, the_day)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["Student", "Program", "Site", "Check-in", "Check-out", "Duration (min)", "Status", "Guardian email"]
    )
    for r in rows:
        writer.writerow(
            [
                r.student_name,
                r.program or "",
                r.site,
                r.check_in.strftime("%m-%d-%Y %H:%M"),
                r.check_out.strftime("%m-%d-%Y %H:%M") if r.check_out else "",
                r.duration_minutes if r.duration_minutes is not None else "",
                r.status,
                r.guardian_email or "(none on file)",
            ]
        )
    buf.seek(0)
    filename = f"attendance_{the_day.isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
