"""Microsoft Graph email backend (EMAIL_BACKEND=graph).

Sends parent notifications through the Graph `sendMail` API using an Azure AD app
and the OAuth client-credentials flow — the durable Microsoft path that survives
the SMTP-AUTH basic-auth shutdown.

Requires (set as GRAPH_* env vars):
  * graph_tenant_id, graph_client_id, graph_client_secret — from an Entra app
    registration whose **Mail.Send application permission has admin consent**.
  * graph_sender — the mailbox to send as (e.g. attendance@squashbusters.org),
    ideally locked to this app via an Application Access Policy.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("attendance.email.graph")

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_SEND_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


class GraphEmailSender:
    """Send via Microsoft Graph. Raises on failure; the notification layer
    catches and logs (a send failure never blocks the kiosk)."""

    def _access_token(self) -> str:
        resp = httpx.post(
            _TOKEN_URL.format(tenant=settings.graph_tenant_id),
            data={
                "client_id": settings.graph_client_id,
                "client_secret": settings.graph_client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        recipients = [
            {"emailAddress": {"address": a.strip()}}
            for a in to.split(",")
            if a.strip()
        ]
        payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML" if html else "Text",
                    "content": html or text,
                },
                "toRecipients": recipients,
            },
            "saveToSentItems": False,
        }
        resp = httpx.post(
            _SEND_URL.format(sender=settings.graph_sender),
            json=payload,
            headers={"Authorization": f"Bearer {self._access_token()}"},
            timeout=20,
        )
        resp.raise_for_status()
