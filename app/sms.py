"""SMS sender backends (L5) — optional second notification channel.

Default backend is "off" — no text is ever sent, so the app runs anywhere with
no cost or setup. Set SMS_BACKEND=console to log texts to the server output, or
SMS_BACKEND=twilio (plus TWILIO_* settings) to actually send.

Mirrors app/email.py so the notification layer treats email and SMS the same way.
Sending real US SMS also requires A2P 10DLC registration and guardian opt-in —
those are operational, not code, concerns.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.config import settings

logger = logging.getLogger("attendance.sms")


class SmsSender(Protocol):
    def send(self, to: str, body: str) -> None: ...


class NullSmsSender:
    """Backend 'off' — silently drops texts (the safe default)."""

    def send(self, to: str, body: str) -> None:  # noqa: D401
        return None


class ConsoleSmsSender:
    """Backend 'console' — logs the text instead of sending. Safe test mode."""

    def send(self, to: str, body: str) -> None:
        logger.info("[SMS - not sent, console backend]\n  To: %s\n  %s", to, body)


class TwilioSmsSender:
    """Backend 'twilio' — sends via the Twilio REST API.

    Imports the SDK lazily so the dependency is only needed when actually used.
    """

    def __init__(self) -> None:
        from twilio.rest import Client  # type: ignore

        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from = settings.twilio_from

    def send(self, to: str, body: str) -> None:
        self._client.messages.create(to=to, from_=self._from, body=body)


def get_sms_sender() -> SmsSender:
    backend = settings.sms_backend.lower()
    if backend == "twilio":
        return TwilioSmsSender()
    if backend == "console":
        return ConsoleSmsSender()
    return NullSmsSender()
