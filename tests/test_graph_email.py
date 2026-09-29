"""Verify the Microsoft Graph email backend builds correct requests (mocked)."""
from app import graph_email
from app.config import settings


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"access_token": "tok123"}


def test_graph_sender_builds_token_and_sendmail_requests(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResp()

    monkeypatch.setattr(graph_email.httpx, "post", fake_post)
    monkeypatch.setattr(settings, "graph_tenant_id", "tid")
    monkeypatch.setattr(settings, "graph_client_id", "cid")
    monkeypatch.setattr(settings, "graph_client_secret", "sec")
    monkeypatch.setattr(settings, "graph_sender", "attendance@sqb.org")

    graph_email.GraphEmailSender().send("a@x.com, b@y.com", "Subj", "plain", "<b>hi</b>")

    # 1) token request (client-credentials)
    turl, tkw = calls[0]
    assert turl == "https://login.microsoftonline.com/tid/oauth2/v2.0/token"
    assert tkw["data"]["grant_type"] == "client_credentials"
    assert tkw["data"]["scope"] == "https://graph.microsoft.com/.default"
    assert tkw["data"]["client_id"] == "cid"

    # 2) sendMail request
    surl, skw = calls[1]
    assert surl == "https://graph.microsoft.com/v1.0/users/attendance@sqb.org/sendMail"
    assert skw["headers"]["Authorization"] == "Bearer tok123"
    msg = skw["json"]["message"]
    assert msg["subject"] == "Subj"
    assert msg["body"]["contentType"] == "HTML"
    assert msg["body"]["content"] == "<b>hi</b>"
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["a@x.com", "b@y.com"]
