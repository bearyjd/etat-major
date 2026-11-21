#!/usr/bin/env python3
"""Record a Claude Code hook payload (JSON on stdin) as one row in a SQLite file.

Only a small allowlist of fields is stored. Tool input, prompts, free-text
notification messages and transcript paths are dropped on purpose: they can
hold secrets or personal paths. The database file is created with mode 0600.
"""

import argparse
import json
import os
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
    notification_type TEXT
)
"""

# Only events that establish or resolve a state count. Anything else (for
# example an idle_prompt or auth_success Notification) is ignored, so it can
# neither raise nor clear an alert. Derived, never stored.
NEEDS_ME_SQL = """
SELECT e.session_id,
       CASE e.event
            WHEN 'Notification' THEN 'needs-you'
            WHEN 'StopFailure' THEN 'failed'
            ELSE 'review'
       END AS state,
       e.ts
FROM events e
WHERE e.id = (
        SELECT MAX(id) FROM events s
        WHERE s.session_id = e.session_id
          AND ((s.event = 'Notification'
                AND s.notification_type IN ('permission_prompt', 'elicitation_dialog'))
               OR s.event IN ('Stop', 'StopFailure', 'UserPromptSubmit',
                              'PreToolUse', 'PostToolUse')))
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
        "notification_type": data.get("notification_type"),
    }


def insert_event(db_path: str, row: dict) -> None:
    # Create the file privately first; sqlite would honour the umask (often 0644).
    os.close(os.open(db_path, os.O_CREAT | os.O_RDWR, 0o600))
    with sqlite3.connect(db_path) as con:
        con.execute(SCHEMA)
        con.execute(
            "INSERT INTO events "
            "(ts, session_id, event, tool_name, cwd, notification_type) "
            "VALUES (:ts, :session_id, :event, :tool_name, :cwd, :notification_type)",
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
