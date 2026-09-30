"""Live-edit (manage) router: edit student, edit/add/remove guardians,
reset PIN, delete student — all behind the staff login."""
import pytest
from fastapi.testclient import TestClient

from app import security
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import Guardian, Site, StaffUser, Student

PASSWORD = "s3cret-pass"


@pytest.fixture()
def seeded(db):
    site = Site(name="Boston")
    db.add(site)
    db.flush()
    student = Student(
        first_name="Ada", last_name="Lovelace", grade="6th Grade",
        active=True, pin_hash=security.hash_pin("1234"), site_id=site.id,
    )
    student.guardians = [
        Guardian(name="Mary Somerville", relationship_type="Mother", email="mary@x.com"),
        Guardian(name="George Byron", relationship_type="Father", phone="555-0001"),
    ]
    db.add(student)
    db.add(StaffUser(username="admin", password_hash=security.hash_password(PASSWORD), role="admin"))
    db.commit()
    return student.id


@pytest.fixture()
def client(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        c.post("/login", data={"username": "admin", "password": PASSWORD})
        yield c
    app.dependency_overrides.clear()


def test_edit_requires_login(db, seeded):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        r = c.get(f"/manage/student/{seeded}", follow_redirects=False)
        assert r.status_code == 303 and "/login" in r.headers["location"]
    app.dependency_overrides.clear()


def test_edit_form_renders(client, seeded):
    r = client.get(f"/manage/student/{seeded}")
    assert r.status_code == 200
    assert "Ada" in r.text and "Mary Somerville" in r.text


def test_update_student_and_guardians(client, seeded, db):
    # Change the student's grade+email, edit guardian 0, remove guardian 1
    # (by omitting it), and add a brand-new guardian.
    r = client.post(
        f"/manage/student/{seeded}",
        data={
            "first_name": "Ada", "last_name": "Byron", "grade": "7th Grade",
            "student_email": "ada@school.edu", "student_phone": "",
            "g-0-id": str(db.get(Student, seeded).guardians[0].id),
            "g-0-name": "Mary Somerville", "g-0-relationship": "Mother",
            "g-0-email": "mary@new.com", "g-0-phone": "",
            # guardian 1 intentionally omitted -> deleted
            "g-2-id": "", "g-2-name": "Aunt Ann", "g-2-relationship": "Aunt",
            "g-2-email": "ann@x.com", "g-2-phone": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    s = db.get(Student, seeded)
    assert s.last_name == "Byron" and s.grade == "7th Grade" and s.email == "ada@school.edu"
    names = {g.name for g in s.guardians}
    assert names == {"Mary Somerville", "Aunt Ann"}  # Byron (father) removed
    mom = next(g for g in s.guardians if g.name == "Mary Somerville")
    assert mom.email == "mary@new.com"


def test_blank_name_is_rejected(client, seeded, db):
    r = client.post(
        f"/manage/student/{seeded}",
        data={"first_name": "", "last_name": "", "grade": "6th Grade"},
        follow_redirects=False,
    )
    assert r.status_code == 303 and "error" in r.headers["location"]
    db.expire_all()
    assert db.get(Student, seeded).first_name == "Ada"  # unchanged


def test_reset_pin_changes_hash_and_shows_once(client, seeded, db):
    old_hash = db.get(Student, seeded).pin_hash
    client.post(f"/manage/student/{seeded}/reset-pin", follow_redirects=False)
    db.expire_all()
    new_hash = db.get(Student, seeded).pin_hash
    assert new_hash and new_hash != old_hash
    # The new PIN is shown exactly once on the next GET, then cleared.
    page = client.get(f"/manage/student/{seeded}").text
    assert "New PIN" in page
    assert "New PIN" not in client.get(f"/manage/student/{seeded}").text


def test_delete_student_cascades(client, seeded, db):
    r = client.post(f"/manage/student/{seeded}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/roster"
    db.expire_all()
    assert db.get(Student, seeded) is None
    assert db.query(Guardian).count() == 0  # guardians cascaded away
