"""Application configuration (Infrastructure layer).

Reads from environment / a local .env file, with sensible dev defaults so the
app runs with zero setup.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SquashBusters Attendance"
    database_url: str = "sqlite:///./attendance.db"

    # Secret for signing the staff login session cookie. Override in production.
    secret_key: str = "dev-secret-change-me-in-production"

    # When true, on startup create the admin user and import the sample roster
    # if the database is empty. Used for the hosted demo so it's self-populating.
    seed_on_startup: bool = False

    # PIN policy
    pin_length: int = 4

    # Minutes that must pass between a check-in and a check-out (prevents
    # accidental instant check-outs from a double-tap).
    time_guard_minutes: int = 30

    # Notifications (L5).
    # "console" = print emails to the server log (safe default, nothing sent).
    # "file"    = save each email as a viewable .html in the outbox (test inbox
    #             at /outbox) — no credentials needed.
    # "smtp"    = actually send via the SMTP settings below.
    email_backend: str = "console"
    outbox_dir: str = "outbox"
    email_from: str = "SquashBusters Attendance <no-reply@squashbusters.org>"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True


settings = Settings()
