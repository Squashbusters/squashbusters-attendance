"""Local-time helpers.

The app runs in a single configured timezone (Boston by default). We generate
times explicitly in that zone via ``zoneinfo`` — not the server's clock — so
check-in times never display in UTC even when the host runs in UTC. The
``tzdata`` package (in requirements) guarantees the zone database exists even on
minimal images that lack the OS one.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings


def local_now() -> datetime:
    """Current wall-clock time in the configured timezone, as a *naive* datetime
    (the app's DateTime columns are naive)."""
    return datetime.now(ZoneInfo(settings.timezone)).replace(tzinfo=None)


def local_today() -> date:
    return local_now().date()
