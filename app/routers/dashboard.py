"""Dashboard & daily verification report (L1 for staff/leadership).

Auth is not wired yet (staff/admin login is the cross-cutting milestone). These
views are read-only reporting over the attendance data.
"""
from __future__ import annotations

import csv
import io
from datetime import date
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
    get_recently_added,
    get_roster,
)
from app.services import process_scan

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
                r.check_in.strftime("%Y-%m-%d %H:%M"),
                r.check_out.strftime("%Y-%m-%d %H:%M") if r.check_out else "",
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
