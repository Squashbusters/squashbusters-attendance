"""Daily attendance digest email.

Builds a summary of the day's attendance and emails it to leadership. Designed
to run once each evening from a Render Cron Job:

    python -m app.daily_digest

By design it only sends on days the system was actually used (at least one
check-in), so quiet days produce no email. Override for testing with --force,
and send to a different address with --to.

Recipients default to DIGEST_RECIPIENTS (comma-separated) or c.restrepo@squashbusters.org.
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, time

from app.clock import local_today
from app.database import SessionLocal
from app.email import get_email_sender
from app.models import AttendanceEvent, Student
from app.reporting import get_daily_rows, get_daily_summary

logger = logging.getLogger("attendance.digest")

DEFAULT_RECIPIENTS = "c.restrepo@squashbusters.org"


def _emails_sent_count(db, day: date) -> int:
    """Notifications sent on `day`: one per check-in and per check-out to a
    student who has at least one guardian email on file."""
    start = datetime.combine(day, time.min)
    end = datetime.combine(day, time.max)

    def has_email(student: Student) -> bool:
        return any(g.email for g in student.guardians)

    check_ins = (
        db.query(AttendanceEvent, Student)
        .join(Student, AttendanceEvent.student_id == Student.id)
        .filter(AttendanceEvent.check_in_at >= start, AttendanceEvent.check_in_at <= end)
        .all()
    )
    check_outs = (
        db.query(AttendanceEvent, Student)
        .join(Student, AttendanceEvent.student_id == Student.id)
        .filter(AttendanceEvent.check_out_at.is_not(None),
                AttendanceEvent.check_out_at >= start, AttendanceEvent.check_out_at <= end)
        .all()
    )
    n = sum(1 for _e, s in check_ins if has_email(s))
    n += sum(1 for _e, s in check_outs if has_email(s))
    return n


def build_digest(db, day: date) -> tuple[str, str, str, int]:
    """Return (subject, text, html, present_count) for the day's digest."""
    s = get_daily_summary(db, day)
    rows = get_daily_rows(db, day)
    emails_sent = _emails_sent_count(db, day)
    pretty = day.strftime("%A, %B %-d, %Y")

    subject = f"SquashBusters attendance, {day.strftime('%b %-d')}: {s['present']} present"

    # ---- plain text ----
    lines = [
        f"SquashBusters Attendance, {pretty}",
        "",
        f"Present today: {s['present']} of {s['total_active']} active ({s['attendance_rate']}%)",
        f"Currently still in the center: {s['still_in']}",
        f"Checked out: {s['checked_out']}",
        f"Notification emails sent to guardians: {emails_sent}",
        f"Students missing a guardian email: {s['missing_email']}",
        "",
        "Attendance:",
    ]
    for r in rows:
        ci = r.check_in.strftime("%-I:%M %p")
        co = r.check_out.strftime("%-I:%M %p") if r.check_out else "still in"
        lines.append(f"  - {r.student_name} ({r.grade or '-'}): in {ci}, out {co}")
    if not rows:
        lines.append("  (no check-ins)")
    text = "\n".join(lines)

    # ---- html ----
    def td(x, b=False):
        return f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;font-size:14px;{"font-weight:600;" if b else ""}">{x}</td>'

    tr_rows = ""
    for r in rows:
        ci = r.check_in.strftime("%-I:%M %p")
        co = r.check_out.strftime("%-I:%M %p") if r.check_out else '<span style="color:#00897b;">still in</span>'
        tr_rows += f"<tr>{td(r.student_name, True)}{td(r.grade or '-')}{td(ci)}{td(co)}</tr>"
    if not rows:
        tr_rows = '<tr><td colspan="4" style="padding:10px;color:#64748b;font-size:14px;">No check-ins recorded.</td></tr>'

    def stat(label, value, color="#0f172a"):
        return (f'<td style="padding:10px 14px;border:1px solid #e2e8f0;border-radius:10px;">'
                f'<div style="font-size:22px;font-weight:700;color:{color};">{value}</div>'
                f'<div style="font-size:12px;color:#64748b;">{label}</div></td>')

    html = f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
  <div style="background:#0f2a4a;color:#fff;padding:16px 20px;font-size:18px;font-weight:600">
    SquashBusters Attendance &mdash; Daily Report
  </div>
  <div style="padding:20px;color:#0f172a;">
    <p style="margin:0 0 14px;color:#475569;font-size:14px;">{pretty}</p>
    <table style="border-spacing:8px;border-collapse:separate;width:100%;margin:0 0 6px;">
      <tr>{stat("Present today", s['present'])}{stat("Still in", s['still_in'], "#00897b")}{stat("Checked out", s['checked_out'])}</tr>
      <tr>{stat("Attendance rate", str(s['attendance_rate']) + '%')}{stat("Emails sent", emails_sent, "#1e6fbf")}{stat("Missing guardian email", s['missing_email'], "#b45309")}</tr>
    </table>
    <h3 style="margin:18px 0 6px;font-size:15px;color:#0f2a4a;">Attendance</h3>
    <table style="width:100%;border-collapse:collapse;">
      <thead><tr style="background:#f1f5f9;">
        <th style="text-align:left;padding:7px 10px;font-size:12px;color:#475569;">Student</th>
        <th style="text-align:left;padding:7px 10px;font-size:12px;color:#475569;">Grade</th>
        <th style="text-align:left;padding:7px 10px;font-size:12px;color:#475569;">Check-in</th>
        <th style="text-align:left;padding:7px 10px;font-size:12px;color:#475569;">Check-out</th>
      </tr></thead>
      <tbody>{tr_rows}</tbody>
    </table>
    <p style="margin:18px 0 0;color:#94a3b8;font-size:12px;">Automatic report from the SquashBusters Attendance system.</p>
  </div>
</div>"""
    return subject, text, html, s["present"]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Send the daily attendance digest.")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today in the program timezone)")
    ap.add_argument("--to", help="Override recipient(s), comma-separated (for testing)")
    ap.add_argument("--force", action="store_true", help="Send even if there were no check-ins")
    args = ap.parse_args()

    day = date.fromisoformat(args.date) if args.date else local_today()
    recipients = args.to or os.environ.get("DIGEST_RECIPIENTS", DEFAULT_RECIPIENTS)
    to = ", ".join(a.strip() for a in recipients.split(",") if a.strip())

    db = SessionLocal()
    try:
        subject, text, html, present = build_digest(db, day)
    finally:
        db.close()

    if present == 0 and not args.force:
        logger.info("No attendance on %s, skipping digest (use --force to send anyway).", day)
        return
    if not to:
        logger.warning("No recipients configured, skipping digest.")
        return

    get_email_sender().send(to, subject, text, html)
    logger.info("Sent daily digest for %s to %s (present=%d).", day, to, present)


if __name__ == "__main__":
    main()
