"""Kiosk page (L1) — serves the tablet check-in interface."""
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_kiosk_access
from app.config import settings

router = APIRouter(tags=["kiosk-ui"], dependencies=[Depends(require_kiosk_access)])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/sqb-kiosk", response_class=HTMLResponse)
def kiosk(request: Request):
    return templates.TemplateResponse(
        "kiosk.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "photo_capture": settings.kiosk_photo_capture,
        },
    )
