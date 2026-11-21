import importlib.util
import io
import json
import os
import re
import sqlite3
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("hook_record", ROOT / "scripts" / "hook_record.py")
hook_record = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook_record)

BASE = {"session_id": "s-alice-1", "cwd": "/work/example-service"}
PRE_TOOL = {
    **BASE,
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "echo token=SECRET"},
}
NOTIFY = {
    **BASE,
    "hook_event_name": "Notification",
    "message": "Claude needs your permission to use Bash",
    "notification_type": "permission_prompt",
}
STOP = {**BASE, "hook_event_name": "Stop"}


def rows(db: Path):
    with sqlite3.connect(db) as con:
        return con.execute("SELECT session_id, event, tool_name FROM events").fetchall()


def run(db: Path, payload, monkeypatch) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return hook_record.main(["--db", str(db)])


def test_inserts_event_row(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    assert run(db, PRE_TOOL, monkeypatch) == 0
    assert rows(db) == [("s-alice-1", "PreToolUse", "Bash")]


def test_does_not_store_tool_input(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    run(db, PRE_TOOL, monkeypatch)
    with sqlite3.connect(db) as con:
        dump = "".join(str(r) for r in con.execute("SELECT * FROM events"))
    assert "SECRET" not in dump


def test_notification_message_not_stored(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    text = "Claude needs permission: password=hunter2-SECRET"
    run(db, {**NOTIFY, "message": text}, monkeypatch)
    with sqlite3.connect(db) as con:
        dump = "".join(str(r) for r in con.execute("SELECT * FROM events"))
        cols = [c[1] for c in con.execute("PRAGMA table_info(events)")]
        out = "".join(str(r) for r in con.execute(hook_record.NEEDS_ME_SQL))
    assert "hunter2" not in dump + out
    assert "message" not in cols


def test_new_database_is_private(tmp_path, monkeypatch):
    old = os.umask(0o022)
    try:
        db = tmp_path / "e.db"
        run(db, NOTIFY, monkeypatch)
    finally:
        os.umask(old)
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_spike_doc_sql_matches_executable_sql():
    doc = (ROOT / "docs" / "spikes" / "phase1-spike.md").read_text()
    block = re.search(r"```sql\n(.*?)```", doc, re.S).group(1)
    norm = lambda q: re.sub(r"\s+", " ", q).strip().rstrip(";").strip()  # noqa: E731
    assert norm(block) == norm(hook_record.NEEDS_ME_SQL)


def test_invalid_json_returns_nonzero_and_writes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hook_record.main(["--db", str(db)]) == 1


def test_missing_fields_rejected(tmp_path, monkeypatch):
    assert run(tmp_path / "e.db", {"cwd": "/x"}, monkeypatch) == 1


def test_non_object_payload_rejected(tmp_path, monkeypatch):
    assert run(tmp_path / "e.db", ["x"], monkeypatch) == 1


def test_requires_db_arg():
    with pytest.raises(SystemExit):
        hook_record.main([])


def test_rollup_what_needs_me(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    run(db, PRE_TOOL, monkeypatch)
    run(db, NOTIFY, monkeypatch)  # s-alice-1 waits on a human
    other = {**STOP, "session_id": "s-alice-2"}
    run(db, other, monkeypatch)  # finished turn -> review
    busy = {**PRE_TOOL, "session_id": "s-alice-3"}
    run(db, busy, monkeypatch)  # still running -> not listed
    resolved = {**NOTIFY, "session_id": "s-alice-4"}
    run(db, resolved, monkeypatch)
    run(db, {**PRE_TOOL, "session_id": "s-alice-4"}, monkeypatch)  # moved on
    with sqlite3.connect(db) as con:
        got = con.execute(hook_record.NEEDS_ME_SQL).fetchall()
    assert [(r[0], r[1]) for r in got] == [("s-alice-1", "needs-you"), ("s-alice-2", "review")]


def needs_me(db):
    with sqlite3.connect(db) as con:
        return [(r[0], r[1]) for r in con.execute(hook_record.NEEDS_ME_SQL)]


def test_auth_success_notification_is_not_an_alert(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    run(db, {**NOTIFY, "notification_type": "auth_success"}, monkeypatch)
    assert needs_me(db) == []


def test_idle_notification_keeps_review_state(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    run(db, STOP, monkeypatch)
    run(db, {**NOTIFY, "notification_type": "idle_prompt"}, monkeypatch)
    assert needs_me(db) == [("s-alice-1", "review")]


def test_idle_notification_does_not_clear_permission_alert(tmp_path, monkeypatch):
    db = tmp_path / "e.db"
    run(db, NOTIFY, monkeypatch)
    run(db, {**NOTIFY, "notification_type": "auth_success"}, monkeypatch)
    assert needs_me(db) == [("s-alice-1", "needs-you")]
