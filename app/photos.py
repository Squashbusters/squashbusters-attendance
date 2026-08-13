"""Check-in photo storage (anti-proxy feature).

Decodes the base64 image captured by the kiosk camera and saves it to the
photos/ directory, returning the filename to store on the attendance record.
"""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

PHOTO_DIR = Path("photos")
_DATA_URL = re.compile(r"data:image/(?P<ext>\w+);base64,(?P<data>.+)", re.S)


def save_photo(data_url: str | None) -> str | None:
    """Save a base64 data-URL image; return its filename (or None)."""
    if not data_url:
        return None
    m = _DATA_URL.match(data_url.strip())
    if not m:
        return None
    ext = "jpg" if m.group("ext") == "jpeg" else m.group("ext")
    try:
        raw = base64.b64decode(m.group("data"))
    except Exception:
        return None
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (PHOTO_DIR / name).write_bytes(raw)
    return name
