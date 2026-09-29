"""Pluggable email sender (Notification layer plumbing, L5).

Default backend is "console" — messages are logged, nothing is sent, so the app
is safe to run anywhere. Set EMAIL_BACKEND=smtp (plus SMTP_* settings) to send
for real.
"""
from __future__ import annotations

import html as html_lib
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from app.clock import local_now
from app.config import settings

logger = logging.getLogger("attendance.email")


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None: ...


class ConsoleEmailSender:
    """Logs the email instead of sending — the default for local/dev."""

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        logger.info(
            "[EMAIL - not sent, console backend]\n  To: %s\n  Subject: %s\n  %s",
            to,
            subject,
            text.replace("\n", "\n  "),
        )


class FileEmailSender:
    """Writes each email to the outbox as a viewable .html file.

    No credentials, nothing sent — a local "test inbox" (see /outbox) that shows
    exactly what a parent would receive.
    """

    def __init__(self, outbox_dir: str | None = None):
        self.outbox = Path(outbox_dir or settings.outbox_dir)

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        self.outbox.mkdir(parents=True, exist_ok=True)
        now = local_now()
        path = self.outbox / (now.strftime("%Y%m%d-%H%M%S-%f") + ".html")

        body = html or f"<pre style='font-family:inherit'>{html_lib.escape(text)}</pre>"
        doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>{html_lib.escape(subject)}</title>
<meta name="x-to" content="{html_lib.escape(to, quote=True)}">
<meta name="x-date" content="{now.isoformat()}">
</head>
<body style="margin:0;background:#f1f5f9;padding:24px;font-family:-apple-system,Segoe UI,Roboto,sans-serif">
<div style="max-width:560px;margin:0 auto">
  <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 18px;margin-bottom:14px;font-size:14px;color:#475569">
    <div><strong>To:</strong> {html_lib.escape(to)}</div>
    <div><strong>Subject:</strong> {html_lib.escape(subject)}</div>
    <div><strong>Sent:</strong> {now:%b %-d, %Y %-I:%M %p} · <em>test outbox — not actually delivered</em></div>
  </div>
  {body}
</div>
</body></html>"""
        path.write_text(doc, encoding="utf-8")
        logger.info("Saved email to test outbox: %s (To: %s)", path.name, to)


class SmtpEmailSender:
    """Sends via SMTP using the configured server."""

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        logger.info("Sent email to %s (subject: %s)", to, subject)


def get_email_sender() -> EmailSender:
    if settings.email_backend == "smtp":
        return SmtpEmailSender()
    if settings.email_backend == "file":
        return FileEmailSender()
    return ConsoleEmailSender()
