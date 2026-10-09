"""Admin area (staff-only): roster CSV upload.

Lets staff load a roster CSV into the running instance — the way real student
data reaches production (through the app, into the database; never through git).
"""
import base64
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import settings
from app.database import get_db
from app.importer import import_roster_csv


def _pin_sheet_csv_b64(created: list[dict]) -> str:
    """Build the assigned-PIN handout as a base64 data-URI payload (one-time download)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student", "Grade", "PIN"])
    for r in created:
        w.writerow([r["name"], r["grade"], r["pin"]])
    return base64.b64encode(buf.getvalue().encode("utf-8")).decode("ascii")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent.parent / "templates")
)


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return templates.TemplateResponse(
        "admin_import.html", {"request": request, "app_name": settings.app_name}
    )


@router.post("/import", response_class=HTMLResponse)
async def import_roster(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a roster CSV — all-or-nothing; a bad row rolls back the whole file."""
    raw = await file.read()
    result = import_roster_csv(db, raw)
    created = result.created if result.ok else []
    return templates.TemplateResponse(
        "admin_import.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "result": result.as_dict(),
            "filename": file.filename,
            "created": created,
            "pin_csv_b64": _pin_sheet_csv_b64(created) if created else "",
        },
    )
