#!/usr/bin/env python3
"""Record one Claude Code hook event into SQLite (allowlisted fields only).

Reads one hook JSON payload on stdin. Stores session_id, hook_event_name,
tool_name (if present) and a UTC timestamp. Nothing else is ever stored.
Exit codes: 0 recorded, 2 invalid input (no DB is created).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime

SCHEMA = """CREATE TABLE IF NOT EXISTS hook_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    hook_event_name TEXT NOT NULL,
    tool_name TEXT,
    timestamp TEXT NOT NULL
)"""


def parse_payload(raw: str) -> tuple[str, str, str | None]:
    """Return (session_id, hook_event_name, tool_name) or raise ValueError."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    session_id = data.get("session_id")
    event = data.get("hook_event_name")
    tool = data.get("tool_name")
    if not isinstance(session_id, str) or not isinstance(event, str):
        raise ValueError("session_id and hook_event_name must be strings")
    if tool is not None and not isinstance(tool, str):
        raise ValueError("tool_name must be a string when present")
    return session_id, event, tool


def record(db_path: str, row: tuple[str, str, str | None]) -> None:
    fd = os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600)
    os.close(fd)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(SCHEMA)
            conn.execute(
                "INSERT INTO hook_events (session_id, hook_event_name, tool_name, timestamp)"
                " VALUES (?, ?, ?, ?)",
                (*row, datetime.now(UTC).isoformat()),
            )
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite file to write")
    args = parser.parse_args(argv)
    try:
        row = parse_payload(sys.stdin.read())
    except ValueError as exc:  # JSONDecodeError is a ValueError
        print(f"hook_record: invalid input: {exc}", file=sys.stderr)
        return 2
    record(args.db, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
