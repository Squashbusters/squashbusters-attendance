"""Authentication & access-gate robustness tests.

Covers the staff login, the admin-only guard, logout, and the production
lockdown (PUBLIC_KIOSK=0 puts the kiosk / API / registration behind login).
"""
import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import StaffUser

PASSWORD = "s3cret-pass"


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    db.add(
        StaffUser(
            username="admin",
            password_hash=security.hash_password(PASSWORD),
            role="admin",
        )
    )
    db.commit()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, password=PASSWORD):
    return client.post(
        "/login",
        data={"username": "admin", "password": password},
        follow_redirects=False,
    )


# --- login ---------------------------------------------------------------
def test_wrong_password_is_rejected(client):
    r = _login(client, password="not-it")
    assert r.status_code == 303
    assert "error" in r.headers["location"]
    # and it did not grant access
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_correct_password_grants_access(client):
    _login(client)
    assert client.get("/dashboard").status_code == 200


def test_logout_clears_session(client):
    _login(client)
    assert client.get("/dashboard").status_code == 200
    client.get("/logout")
    assert client.get("/dashboard", follow_redirects=False).status_code == 303


# --- protected routes always require login -------------------------------
@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/roster", "/admin/import", "/report/daily"])
def test_staff_routes_require_login(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


# --- production lockdown (PUBLIC_KIOSK=0) ---------------------------------
@pytest.mark.parametrize("path", ["/", "/register", "/api/students", "/api/dashboard/summary"])
def test_kiosk_locked_when_public_kiosk_off(client, monkeypatch, path):
    monkeypatch.setattr(settings, "public_kiosk", False)
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_kiosk_open_when_public_kiosk_on(client, monkeypatch):
    monkeypatch.setattr(settings, "public_kiosk", True)
    assert client.get("/").status_code == 200
    assert client.get("/api/students").status_code == 200


def test_logged_in_staff_can_use_locked_kiosk(client, monkeypatch):
    monkeypatch.setattr(settings, "public_kiosk", False)
    _login(client)
    assert client.get("/").status_code == 200
    assert client.get("/api/students").status_code == 200
