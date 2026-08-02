"""Staff/admin authentication (Security layer).

Session-cookie login protecting the leadership/admin pages. The student kiosk
(`/`, `/api/*`) stays open — students never log in.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from app import security
from app.config import settings
from app.database import get_db
from app.models import StaffUser

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)


class NotAuthenticated(Exception):
    """Raised by guards when a protected page is hit without a session."""


def require_login(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    return user


def require_admin(request: Request) -> dict:
    user = require_login(request)
    if user.get("role") != "admin":
        raise NotAuthenticated()
    return user


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "app_name": settings.app_name, "error": error},
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(StaffUser).filter(StaffUser.username == username).first()
    if user is None or not security.verify_password(password, user.password_hash):
        return RedirectResponse("/login?error=1", status_code=303)
    request.session["user"] = {"username": user.username, "role": user.role}
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
