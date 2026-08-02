"""Kiosk page (L1) — serves the tablet check-in interface."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

router = APIRouter(tags=["kiosk-ui"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def kiosk(request: Request):
    return templates.TemplateResponse(
        "kiosk.html",
        {"request": request, "app_name": settings.app_name},
    )
