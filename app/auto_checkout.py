"""Nightly auto-checkout.

Closes any attendance events still open (checked in but never checked out) at
the end of the day, so a forgotten check-out doesn't linger as "still in" and
skew the next day's counts. Designed to run once each night from a Render Cron
Job (same pattern as the daily digest):

    python -m app.auto_checkout

Silent by design: it does NOT email guardians (nobody wants a 10 PM "checked
out" message). Idempotent — a run with nothing open changes nothing. Use
--dry-run to see how many would be closed without changing anything.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime

from app.clock import local_now
from app.database import SessionLocal
from app.models import AttendanceEvent

logger = logging.getLogger("attendance.auto_checkout")


def run_auto_checkout(db, at: datetime | None = None) -> list[int]:
    """Close every open attendance event (check_out_at IS NULL).

    Sets check_out_at to `at` (defaults to the local wall-clock time of the run).
    Returns the ids of the events that were closed. No guardian notifications are
    sent — this is an administrative end-of-day sweep, not a real check-out.
    """
    when = at or local_now()
    open_events = (
        db.query(AttendanceEvent)
        .filter(AttendanceEvent.check_out_at.is_(None))
        .all()
    )
    for event in open_events:
        event.check_out_at = when
    db.commit()
    return [e.id for e in open_events]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Check out everyone still checked in (end-of-day sweep)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report how many check-ins would be closed, change nothing.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.dry_run:
            n = (
                db.query(AttendanceEvent)
                .filter(AttendanceEvent.check_out_at.is_(None))
                .count()
            )
            logger.info("[dry-run] %d open check-in(s) would be closed.", n)
            return
        closed = run_auto_checkout(db)
        logger.info(
            "Auto-checkout closed %d open check-in(s) at %s.",
            len(closed), local_now().strftime("%Y-%m-%d %H:%M"),
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
