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


def require_kiosk_access(request: Request) -> None:
    """Gate the kiosk/API/registration.

    Open when PUBLIC_KIOSK is true (local/demo). In production (PUBLIC_KIOSK=0)
    it requires a staff session, so student names never appear on a public URL —
    the tablet is signed in once per shift.
    """
    if settings.public_kiosk:
        return
    require_login(request)


def _safe_next(nxt: str | None, default: str = "/dashboard") -> str:
    """Only allow same-site relative paths as a post-login redirect target."""
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return default


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None, next: str | None = None):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "error": error,
            "next": next,
        },
    )


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    db: Session = Depends(get_db),
):
    user = db.query(StaffUser).filter(StaffUser.username == username).first()
    if user is None or not security.verify_password(password, user.password_hash):
        from urllib.parse import quote

        suffix = f"&next={quote(next, safe='')}" if next else ""
        return RedirectResponse(f"/login?error=1{suffix}", status_code=303)
    request.session["user"] = {"username": user.username, "role": user.role}
    # Return to the page they originally opened (kiosk link -> kiosk, etc.).
    return RedirectResponse(_safe_next(next), status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
