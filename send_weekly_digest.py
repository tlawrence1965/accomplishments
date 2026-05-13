#!/usr/bin/env python3
"""
Weekly accomplishment digest.

Queries the accomplishments database for entries from the past 7 days
and emails them via Resend. Designed to be run from cron.

Cron line (Fridays at 4pm):
    0 16 * * 5 /usr/bin/python3 /opt/tracker/send_weekly_digest.py >> /var/log/tracker-digest.log 2>&1
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# --- Config (read from environment, with sensible defaults) ---------------
DB_PATH = os.environ.get("TRACKER_DB_PATH", "/opt/tracker/tracker.db")
RESEND_API_KEY = os.environ["RESEND_API_KEY"]            # required
FROM_ADDRESS = os.environ["DIGEST_FROM"]                 # e.g. "tracker@yourdomain.com"
TO_ADDRESS = os.environ["DIGEST_TO"]                     # your real inbox
TABLE_NAME = os.environ.get("TRACKER_TABLE", "accomplishments")

# Adjust these column names to whatever your schema actually uses.
DATE_COLUMN = os.environ.get("TRACKER_DATE_COL", "created_at")
TEXT_COLUMN = os.environ.get("TRACKER_TEXT_COL", "description")


def fetch_week(db_path: str) -> list[tuple[datetime, str]]:
    """Return (date, description) rows from the last 7 days, oldest first."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    conn = sqlite3.connect(db_path)
    try:
        # SQLite stores datetimes as text; ISO-8601 strings sort correctly.
        cursor = conn.execute(
            f"SELECT {DATE_COLUMN}, {TEXT_COLUMN} "
            f"FROM {TABLE_NAME} "
            f"WHERE {DATE_COLUMN} >= ? "
            f"ORDER BY {DATE_COLUMN} ASC",
            (cutoff.isoformat(),),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    parsed = []
    for raw_date, text in rows:
        # Handle both ISO strings and any stray datetime objects
        if isinstance(raw_date, str):
            # fromisoformat handles "2026-05-09T14:30:00+00:00" and similar
            dt = datetime.fromisoformat(raw_date)
        else:
            dt = raw_date
        parsed.append((dt, text))
    return parsed


def format_email(entries: list[tuple[datetime, str]]) -> tuple[str, str]:
    """Return (plain_text, html) versions of the digest body."""
    now = datetime.now()
    week_ending = now.strftime("%B %d, %Y")

    if not entries:
        plain = (
            f"Week ending {week_ending}\n\n"
            "No accomplishments logged this week. "
            "If that's wrong, the tracker may be down — worth checking.\n"
        )
        html = (
            f"<h2>Week ending {week_ending}</h2>"
            "<p>No accomplishments logged this week. "
            "If that's wrong, the tracker may be down — worth checking.</p>"
        )
        return plain, html

    # Plain text version
    plain_lines = [f"Week ending {week_ending}", "", f"{len(entries)} entries:", ""]
    for dt, text in entries:
        plain_lines.append(f"  [{dt.strftime('%a %m/%d')}] {text}")
    plain = "\n".join(plain_lines) + "\n"

    # HTML version — keep it minimal; email clients are hostile to fancy CSS
    html_items = "".join(
        f"<li><strong>{dt.strftime('%a %m/%d')}</strong> &mdash; "
        f"{escape_html(text)}</li>"
        for dt, text in entries
    )
    html = (
        f"<h2>Week ending {week_ending}</h2>"
        f"<p>{len(entries)} entries:</p>"
        f"<ul>{html_items}</ul>"
    )
    return plain, html


def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def send_via_resend(subject: str, plain: str, html: str) -> None:
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": FROM_ADDRESS,
            "to": [TO_ADDRESS],
            "subject": subject,
            "text": plain,
            "html": html,
        },
        timeout=30,
    )
    response.raise_for_status()


def main() -> int:
    if not Path(DB_PATH).exists():
        print(f"[{datetime.now().isoformat()}] ERROR: db not found at {DB_PATH}",
              file=sys.stderr)
        return 1

    entries = fetch_week(DB_PATH)
    plain, html = format_email(entries)
    subject = f"Weekly accomplishments — {datetime.now().strftime('%b %d')}"

    try:
        send_via_resend(subject, plain, html)
    except requests.HTTPError as e:
        print(f"[{datetime.now().isoformat()}] Resend rejected: "
              f"{e.response.status_code} {e.response.text}", file=sys.stderr)
        return 2
    except requests.RequestException as e:
        print(f"[{datetime.now().isoformat()}] network error: {e}", file=sys.stderr)
        return 3

    print(f"[{datetime.now().isoformat()}] sent {len(entries)} entries to {TO_ADDRESS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
