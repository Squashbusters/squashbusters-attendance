"""Admin API (L1/L2 slice for M1): roster CSV bulk-import.

Auth is intentionally not wired yet — that lands with the cross-cutting
staff/admin login milestone. For now this is a local-only admin endpoint.
"""
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.importer import import_roster_csv

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/import")
async def import_roster(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict:
    """Upload a roster CSV. Returns a summary of imports, errors, and warnings.

    The import is all-or-nothing: if any row has a hard error, nothing is
    committed and the errors are returned so the file can be fixed and retried.
    """
    raw = await file.read()
    result = import_roster_csv(db, raw)
    return {"ok": result.ok, "filename": file.filename, **result.as_dict()}
