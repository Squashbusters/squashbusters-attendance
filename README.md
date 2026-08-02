# SquashBusters Attendance Check-In System

A tablet-kiosk attendance system: a student selects their name, enters a secure
PIN, and is automatically checked in or out. Arrivals/departures notify parents
by email and feed leadership dashboards. Multi-site ready.

See the architecture gameplan for the full 7-layer design. This repo is being
built milestone by milestone.

## Status

- [x] **M1 — Foundation & data**: FastAPI scaffold, data model, PIN hashing, CSV bulk import.
- [x] **M2 — Domain logic**: check-in/out decision + 30-min time guard (pure, tested).
- [x] **M3 — Kiosk UI + API**: name select -> PIN pad -> confirmation, single /checkin endpoint.
- [x] **M4 — Dashboard + daily report**: live metrics + printable/CSV verification report.
- [x] **M5 — Parent notifications**: guardian email on every check-in/out (console or SMTP).

### Deferred (not yet built)
- Salesforce-report importer + column mapping (roster will come from a Salesforce report).
- PIN onboarding model (auto-generate vs student-set) — core PIN storage/verify is done.
- Staff/admin authentication on the dashboard, report, and admin endpoints.

## Key URLs

- Kiosk:          http://localhost:8000/
- Dashboard:      http://localhost:8000/dashboard
- Daily report:   http://localhost:8000/report/daily
- API docs:       http://localhost:8000/docs

## Deploying live (shareable link for stakeholders)

`localhost` only works on the machine running the app. To give someone else a
clickable link, deploy to a host like Render (free tier), which builds straight
from this GitHub repo.

Steps on Render (render.com):
1. New → Web Service → connect this repo.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (already in `Procfile`).
4. Add a **Postgres** database (Render provides one free) and add the Postgres
   driver to `requirements.txt`: `psycopg2-binary`.
5. Set environment variables (NOT committed — set them in Render's dashboard):
   - `DATABASE_URL` = the Render Postgres URL
   - `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
   - `TIME_GUARD_MINUTES=30`
6. Deploy → Render gives you a URL like `https://squashbusters-attendance.onrender.com`.
7. Seed the roster once (Render Shell): `python -m app.seed`.

Before sharing publicly, add staff/admin login (the dashboard/report/admin pages
are currently open) — see the deferred list above.

## Enabling real parent emails

Emails are logged (not sent) by default. To send for real, set in `.env`:

```
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-16-char-app-password   # Gmail App Password, not your login
```

## Setup

```bash
cd attendance_system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; defaults work out of the box
```

## Seed the database from the sample roster

```bash
python -m app.seed
```

This creates `attendance.db` (SQLite), a default admin user (`admin` / `changeme`),
and imports the 10 sample students in `data/sample_roster.csv`.

## Run the API

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs to try the admin CSV import endpoint
(`POST /admin/import`).

## Run the tests

```bash
pytest
```

## Roster CSV format

Columns: `first_name, last_name, program, site, guardian_email, pin`

- PINs must be exactly 4 digits and not trivially guessable (no `0000`, `1234`).
- PINs are hashed on import — the database never stores a readable PIN.
- Duplicate names within a site, missing names, and bad PINs are hard errors
  that block the whole import (fix and retry).
- Missing/invalid guardian emails are warnings — the student is still imported
  but flagged (no notifications until fixed).
