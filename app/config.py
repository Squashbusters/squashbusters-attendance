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

    # When true, on startup ensure the admin user exists (and, if seed_sample_roster
    # is also true, import the sample roster when the DB is empty).
    seed_on_startup: bool = False
    # Only load the 10-student sample roster in demo mode. Turn OFF in production
    # so real data isn't mixed with fake students.
    seed_sample_roster: bool = True

    # Staff/admin account created on first startup. Override the password in
    # production via the ADMIN_PASSWORD env var — never leave it as "changeme".
    admin_username: str = "admin"
    admin_password: str = "changeme"

    # When true (local/demo), the kiosk and its API are open with no login — handy
    # for testing. Set PUBLIC_KIOSK=0 in production so the whole app is behind the
    # staff login (the tablet is signed in once per shift), keeping student names
    # off a public URL.
    public_kiosk: bool = True

    # The single timezone the program operates in — all check-in times are
    # recorded and displayed in this zone (not the server's UTC).
    timezone: str = "America/New_York"

    # PIN policy
    pin_length: int = 4

    # When true, the kiosk takes a photo at check-in (anti-proxy). Disabled for
    # now — no camera prompt, no image captured. Flip via env to re-enable.
    kiosk_photo_capture: bool = False

    # Grades the kiosk always shows on the landing screen, in order. Tiles appear
    # even when a grade has no students yet (shown but disabled), so the board is
    # consistent for staff and students. Comma-separated; override via env.
    kiosk_grades: str = (
        "5th Grade,6th Grade,7th Grade,8th Grade,9th Grade,"
        "10th Grade,11th Grade,12th Grade"
    )

    @property
    def kiosk_grade_list(self) -> list[str]:
        return [g.strip() for g in self.kiosk_grades.split(",") if g.strip()]

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

    # Microsoft Graph email backend (EMAIL_BACKEND=graph). Uses an Azure AD app
    # (client-credentials OAuth) with Mail.Send application permission + admin
    # consent. graph_sender is the mailbox to send from.
    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_sender: str = ""

    # SMS notifications (optional second channel to guardian phones).
    # "off"     = never send a text (default — no cost, no setup).
    # "console" = log the text to the server output (safe test mode).
    # "twilio"  = actually send via the Twilio settings below.
    # NOTE: real US SMS also requires A2P 10DLC registration and guardian opt-in.
    sms_backend: str = "off"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""  # your Twilio phone number, e.g. +16175551234


settings = Settings()
