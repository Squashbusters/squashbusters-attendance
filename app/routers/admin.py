"""Admin API (staff-only): roster CSV bulk-import.

Walk-in registration moved to the open public router (app/routers/register.py),
reachable from both the kiosk and the dashboard.
"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.importer import import_roster_csv

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/import")
async def import_roster(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a roster CSV. Returns a summary of imports, errors, and warnings."""
    raw = await file.read()
    result = import_roster_csv(db, raw)
    return {"ok": result.ok, "filename": file.filename, **result.as_dict()}
