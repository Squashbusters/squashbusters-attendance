"""Seed the database from the sample roster CSV.

Usage:
    python -m app.seed              # imports data/sample_roster.csv
    python -m app.seed path/to.csv  # imports a specific file

Also creates a default admin staff user (admin / changeme) if none exists.
"""
import sys
from pathlib import Path

from app.database import SessionLocal, init_db
from app.importer import import_roster_csv
from app.models import StaffUser
from app.security import hash_password

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "sample_roster.csv"


def ensure_admin(db) -> None:
    from app.config import settings
    from app.security import verify_password

    admin = (
        db.query(StaffUser).filter(StaffUser.username == settings.admin_username).first()
    )
    if admin is None:
        db.add(
            StaffUser(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="admin",
            )
        )
        db.commit()
        note = " (change this!)" if settings.admin_password == "changeme" else ""
        print(f"Created admin user: {settings.admin_username}{note}")
        return

    # Admin exists: if a real ADMIN_PASSWORD is set and differs, update it so the
    # env var stays the source of truth (fixes the "already created as changeme" case).
    if settings.admin_password != "changeme" and not verify_password(
        settings.admin_password, admin.password_hash
    ):
        admin.password_hash = hash_password(settings.admin_password)
        db.commit()
        print("Updated admin password from ADMIN_PASSWORD.")


def seed_if_empty() -> None:
    """Idempotent seed for the hosted demo: ensure an admin exists and, if there
    are no students yet, import the sample roster."""
    from app.models import Student

    from app.config import settings

    init_db()
    db = SessionLocal()
    try:
        ensure_admin(db)
        if settings.seed_sample_roster and db.query(Student).count() == 0:
            import_roster_csv(db, DEFAULT_CSV.read_bytes())
            print("Seeded sample roster on startup.")
    finally:
        db.close()


def main() -> None:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    init_db()
    db = SessionLocal()
    try:
        ensure_admin(db)
        result = import_roster_csv(db, csv_path.read_bytes())
        summary = result.as_dict()
        print(f"Imported {summary['imported']} student(s) from {csv_path.name}")
        if summary["warnings"]:
            print(f"  {summary['warning_count']} warning(s):")
            for w in summary["warnings"]:
                print(f"    line {w['line']}: {w['message']}")
        if summary["errors"]:
            print(f"  {summary['error_count']} error(s) — nothing imported:")
            for e in summary["errors"]:
                print(f"    line {e['line']}: {e['message']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
