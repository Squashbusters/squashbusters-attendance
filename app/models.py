"""ORM models — the Data/Persistence layer (L4).

Every operational record carries a site_id so the system is multi-site ready
(Boston now; Lawrence / Providence are just new Site rows later).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    students: Mapped[list["Student"]] = relationship(back_populates="site")


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)

    students: Mapped[list["Student"]] = relationship(back_populates="program")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    # Grade label as it comes from Salesforce, e.g. "6th Grade". Nullable so a
    # student can exist without one; the kiosk groups the name picker by grade.
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # Student's own contact details (captured at walk-in registration).
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When this student was added (walk-in registration) — powers "recently added".
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=True
    )
    # Reference fields carried over from Salesforce (nullable — walk-ins won't have them).
    contact_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    current_program_status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contact_record_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    program_engagement_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Never store a readable PIN — only its hash. Nullable so a student can
    # exist before a PIN is set (supports the deferred onboarding decision).
    pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id"), nullable=True, index=True
    )

    site: Mapped["Site"] = relationship(back_populates="students")
    program: Mapped["Program | None"] = relationship(back_populates="students")
    guardians: Mapped[list["Guardian"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    attendance_events: Mapped[list["AttendanceEvent"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Guardian(Base):
    __tablename__ = "guardians"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Mother / Father / Other (free text for "Other", e.g. Aunt, Grandparent).
    # Attribute is renamed to avoid shadowing SQLAlchemy's relationship(); the DB
    # column stays "relationship".
    relationship_type: Mapped[str | None] = mapped_column(
        "relationship", String(40), nullable=True
    )
    # Required in practice for notifications; nullable in the schema so a
    # check-in is never blocked purely by a missing email (it's flagged instead).
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Guardian mobile — used for the optional SMS notification channel.
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="guardians")


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"), index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)

    check_in_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    check_out_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    session_type: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Anti-proxy: photo captured at the kiosk on check-in / check-out.
    check_in_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    check_out_photo: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    student: Mapped["Student"] = relationship(
        back_populates="attendance_events"
    )

    @property
    def is_open(self) -> bool:
        """An 'open' event = checked in but not yet checked out."""
        return self.check_out_at is None


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # "staff" = read dashboards/reports; "admin" = manage data + import.
    role: Mapped[str] = mapped_column(String(20), default="staff")
