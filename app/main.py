"""FastAPI application entry point."""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.config import settings
from app.database import init_db
from app.routers import admin, api, dashboard, kiosk, outbox, register

# Surface our INFO logs (e.g. the console email backend) in the server output.
logging.getLogger("attendance").setLevel(logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


@app.exception_handler(auth.NotAuthenticated)
def _redirect_to_login(request: Request, exc: auth.NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


app.include_router(kiosk.router)
app.include_router(register.router)
app.include_router(api.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(outbox.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    if settings.seed_on_startup:
        from app.seed import seed_if_empty

        seed_if_empty()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
