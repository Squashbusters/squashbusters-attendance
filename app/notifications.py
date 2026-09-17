"""Parent notification layer (L5).

On every check-in and check-out, a branded email goes to the guardian. This is
both the parents' running attendance record and the real-time anti-proxy alarm.
Sending is best-effort: a missing address or a send failure is logged, never
raised, so the kiosk is never blocked by email.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from app.email import EmailSender, get_email_sender
from app.services import ScanResult, ScanStatus
from app.sms import SmsSender, get_sms_sender

logger = logging.getLogger("attendance.notifications")


@dataclass
class NotificationPayload:
    to_emails: list[str]  # every guardian with an email on file
    to_phones: list[str]  # every guardian with a phone on file (SMS channel)
    first_name: str
    full_name: str
    site_name: str
    action: str  # "checked in" | "checked out"
    event_time: datetime


def payload_from_result(result: ScanResult) -> NotificationPayload | None:
    """Build a self-contained payload from a scan result.

    Returns None if this result is not a check-in/out that warrants an email.
    Reads the ORM relationships while the session is still open, so the payload
    can be sent later (e.g. in a background task) without a DB session.
    """
    if result.status not in (ScanStatus.CHECKED_IN, ScanStatus.CHECKED_OUT):
        return None
    student = result.student
    event = result.event
    assert student is not None and event is not None

    to_emails = [g.email for g in student.guardians if g.email]
    to_phones = [g.phone for g in student.guardians if g.phone]
    action = "checked in" if result.status is ScanStatus.CHECKED_IN else "checked out"
    event_time = event.check_in_at if result.status is ScanStatus.CHECKED_IN else event.check_out_at

    return NotificationPayload(
        to_emails=to_emails,
        to_phones=to_phones,
        first_name=student.first_name,
        full_name=student.full_name,
        site_name=student.site.name,
        action=action,
        event_time=event_time,
    )


def build_email(p: NotificationPayload) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for a notification."""
    when = p.event_time.strftime("%A, %B %-d, %Y at %-I:%M %p")
    verb = "arrived at" if p.action == "checked in" else "left"
    subject = f"{p.full_name} {p.action} — SquashBusters"

    text = (
        f"Hi,\n\n"
        f"This is an automatic notification from SquashBusters.\n\n"
        f"{p.full_name} {p.action} ({verb} the {p.site_name} center) on {when}.\n\n"
        f"If you did not expect this, please contact SquashBusters staff.\n\n"
        f"— SquashBusters Attendance"
    )

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;
            border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
  <div style="background:#0f172a;color:#fff;padding:18px 22px;font-size:18px;font-weight:600">
    SquashBusters Attendance
  </div>
  <div style="padding:22px;color:#0f172a;font-size:15px;line-height:1.6">
    <p style="margin:0 0 14px">Hi,</p>
    <p style="margin:0 0 14px">
      <strong>{p.full_name}</strong> {p.action} ({verb} the {p.site_name} center).
    </p>
    <p style="margin:0 0 6px;color:#475569">{when}</p>
    <p style="margin:18px 0 0;color:#64748b;font-size:13px">
      If you did not expect this, please contact SquashBusters staff.
    </p>
  </div>
</div>"""
    return subject, text, html


def build_sms(p: NotificationPayload) -> str:
    """Short plain-text body for the SMS channel."""
    when = p.event_time.strftime("%-I:%M %p")
    return (
        f"SquashBusters: {p.full_name} {p.action} at the {p.site_name} center "
        f"({when}). Reply STOP to opt out."
    )


def send_sms_notification(payload: NotificationPayload, sender: SmsSender | None = None) -> bool:
    """Send the SMS copy of a notification to every guardian phone on file.

    Best-effort and never raises — a missing number or provider error is logged
    and swallowed so the kiosk is never affected. Does nothing when SMS_BACKEND
    is "off" (the NullSmsSender), so this is a no-op until explicitly enabled.
    """
    if not payload.to_phones:
        return False
    sender = sender or get_sms_sender()
    body = build_sms(payload)
    sent = False
    for number in payload.to_phones:
        try:
            sender.send(number, body)
            sent = True
        except Exception:  # best-effort per recipient
            logger.exception("Failed to send SMS to %s", number)
    return sent


def send_notification(payload: NotificationPayload, sender: EmailSender | None = None) -> bool:
    """Send one notification. Returns True if an email was sent/logged.

    Never raises — a missing address or SMTP error is logged and swallowed so the
    check-in experience is never affected.
    """
    if not payload.to_emails:
        logger.warning(
            "No guardian email for %s — notification skipped (flagged in daily report).",
            payload.full_name,
        )
        return False

    sender = sender or get_email_sender()
    subject, text, html = build_email(payload)
    recipients = ", ".join(payload.to_emails)
    try:
        sender.send(recipients, subject, text, html)
        return True
    except Exception:  # best-effort: log and move on
        logger.exception("Failed to send notification to %s", recipients)
        return False
