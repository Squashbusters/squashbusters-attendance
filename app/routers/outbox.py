"""Test outbox viewer (L1) — a local "inbox" for the file email backend.

Lets you see exactly what parents would receive, with no email account.
Only meaningful when EMAIL_BACKEND=file.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.config import settings

router = APIRouter(tags=["outbox"])

_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_TO = re.compile(r'name="x-to" content="(.*?)"')
_DATE = re.compile(r'name="x-date" content="(.*?)"')


def _outbox() -> Path:
    return Path(settings.outbox_dir)


@router.get("/outbox", response_class=HTMLResponse)
def outbox_index():
    box = _outbox()
    files = (
        sorted(box.glob("*.html"), key=os.path.getmtime, reverse=True)
        if box.exists()
        else []
    )

    rows = ""
    for f in files:
        txt = f.read_text(encoding="utf-8")
        subject = (_TITLE.search(txt) or [None, "(no subject)"])[1].strip()
        to = (_TO.search(txt) or [None, "?"])[1]
        date = (_DATE.search(txt) or [None, ""])[1][:19].replace("T", " ")
        rows += (
            f'<a class="row" href="/outbox/{f.name}" target="preview">'
            f'<div class="subj">{subject}</div>'
            f'<div class="meta">To: {to} · {date}</div></a>'
        )

    if not rows:
        rows = '<div class="empty">No emails yet. Check a student in on the kiosk, then refresh.</div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Test outbox</title>
<style>
  body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f172a;color:#f1f5f9;
    display:grid;grid-template-columns:340px 1fr;height:100vh}}
  .list{{border-right:1px solid #334155;overflow-y:auto}}
  .head{{padding:18px 20px;border-bottom:1px solid #334155;font-size:17px;font-weight:600}}
  .row{{display:block;padding:14px 20px;border-bottom:1px solid #1e293b;text-decoration:none;color:inherit}}
  .row:hover{{background:#1e293b}}
  .subj{{font-size:15px;margin-bottom:4px}}
  .meta{{font-size:12px;color:#94a3b8}}
  .empty{{padding:30px 20px;color:#94a3b8}}
  iframe{{width:100%;height:100%;border:none;background:#f1f5f9}}
</style></head>
<body>
  <div class="list">
    <div class="head">Test outbox · {len(files)} email(s)</div>
    {rows}
  </div>
  <iframe name="preview" {'src="/outbox/'+files[0].name+'"' if files else ''}></iframe>
</body></html>"""


@router.get("/outbox/{name}", response_class=HTMLResponse)
def outbox_email(name: str):
    # Prevent path traversal — only serve plain .html files from the outbox.
    if "/" in name or "\\" in name or not name.endswith(".html"):
        raise HTTPException(status_code=400, detail="Invalid file")
    path = _outbox() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="text/html")
