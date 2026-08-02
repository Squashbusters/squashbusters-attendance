"""FastAPI application entry point."""
import logging

from fastapi import FastAPI

from app.config import settings
from app.database import init_db
from app.routers import admin, api, dashboard, kiosk, outbox

# Surface our INFO logs (e.g. the console email backend) in the server output.
logging.getLogger("attendance").setLevel(logging.INFO)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.app_name)
app.include_router(kiosk.router)
app.include_router(api.router)
app.include_router(dashboard.router)
app.include_router(outbox.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
