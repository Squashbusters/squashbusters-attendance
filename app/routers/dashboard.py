"""Dashboard & daily verification report (L1 for staff/leadership).

Auth is not wired yet (staff/admin login is the cross-cutting milestone). These
views are read-only reporting over the attendance data.
"""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from app.auth import require_login
from app.config import settings
from app.database import get_db
from app.reporting import get_daily_rows, get_daily_summary

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_login)])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


def _parse_day(day: str | None) -> date:
    if not day:
        return date.today()
    try:
        return date.fromisoformat(day)
    except ValueError:
        return date.today()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, day: str | None = None, db: Session = Depends(get_db)):
    the_day = _parse_day(day)
    summary = get_daily_summary(db, the_day)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "summary": summary,
            "day": the_day.isoformat(),
        },
    )


@router.get("/api/dashboard/summary")
def dashboard_summary(day: str | None = None, site_id: int | None = None, db: Session = Depends(get_db)):
    return get_daily_summary(db, _parse_day(day), site_id)


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
