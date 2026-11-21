#!/usr/bin/env python3
"""Record a Claude Code hook payload (JSON on stdin) as one row in a SQLite file.

Only a small allowlist of fields is stored. Tool input, prompts and transcript
paths are dropped on purpose: they can hold secrets or personal paths.
"""

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event TEXT NOT NULL,
    tool_name TEXT,
    cwd TEXT,
    message TEXT
)
"""

# One row per session whose latest event wants a human. Derived, never stored.
NEEDS_ME_SQL = """
SELECT e.session_id,
       CASE e.event
            WHEN 'Notification' THEN 'needs-you'
            WHEN 'StopFailure' THEN 'failed'
            ELSE 'review'
       END AS state,
       e.ts, e.message
FROM events e
WHERE e.id = (SELECT MAX(id) FROM events WHERE session_id = e.session_id)
  AND e.event IN ('Notification', 'Stop', 'StopFailure')
ORDER BY e.id
"""


def parse_payload(raw: str) -> dict | None:
    """Return the event fields to store, or None if the payload is unusable."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    session, event = data.get("session_id"), data.get("hook_event_name")
    if not session or not event:
        return None
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_id": str(session),
        "event": str(event),
        "tool_name": data.get("tool_name"),
        "cwd": data.get("cwd"),
        "message": data.get("message"),
    }


def insert_event(db_path: str, row: dict) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(SCHEMA)
        con.execute(
            "INSERT INTO events (ts, session_id, event, tool_name, cwd, message) "
            "VALUES (:ts, :session_id, :event, :tool_name, :cwd, :message)",
            row,
        )
    con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="path of the SQLite file")
    args = parser.parse_args(argv)
    row = parse_payload(sys.stdin.read())
    if row is None:
        print("hook_record: invalid hook payload", file=sys.stderr)
        return 1
    insert_event(args.db, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
