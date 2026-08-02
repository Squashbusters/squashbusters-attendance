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
    if db.query(StaffUser).filter(StaffUser.username == "admin").first():
        return
    db.add(
        StaffUser(
            username="admin",
            password_hash=hash_password("changeme"),
            role="admin",
        )
    )
    db.commit()
    print("Created default admin user: admin / changeme  (change this!)")


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
