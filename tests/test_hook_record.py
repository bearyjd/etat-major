import json
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hook_record.py"


def run(db: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--db", str(db)],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def rows(db: Path) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        cur = conn.execute(
            "SELECT session_id, hook_event_name, tool_name, timestamp FROM hook_events"
        )
        return cur.fetchall()


def test_valid_payload_inserts_allowlisted_row(tmp_path):
    db = tmp_path / "events.db"
    payload = {"session_id": "s-alice", "hook_event_name": "PreToolUse", "tool_name": "Bash"}
    result = run(db, json.dumps(payload))
    assert result.returncode == 0
    (row,) = rows(db)
    assert row[:3] == ("s-alice", "PreToolUse", "Bash")
    assert row[3]


def test_tool_name_optional(tmp_path):
    db = tmp_path / "events.db"
    run(db, json.dumps({"session_id": "s1", "hook_event_name": "Stop"}))
    assert rows(db)[0][2] is None


def test_db_created_with_mode_0600(tmp_path):
    db = tmp_path / "events.db"
    run(db, json.dumps({"session_id": "s1", "hook_event_name": "Stop"}))
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_invalid_json_exits_nonzero_without_db(tmp_path):
    db = tmp_path / "events.db"
    assert run(db, "{not json").returncode != 0
    assert not db.exists()


def test_non_object_json_rejected(tmp_path):
    db = tmp_path / "events.db"
    assert run(db, "[1, 2]").returncode != 0
    assert not db.exists()


def test_wrong_field_types_rejected_without_db(tmp_path):
    db = tmp_path / "events.db"
    bad = [
        {"session_id": 1, "hook_event_name": "Stop"},
        {"session_id": "s1", "hook_event_name": None},
        {"session_id": "s1"},
        {"hook_event_name": "Stop"},
        {"session_id": "s1", "hook_event_name": "Stop", "tool_name": 5},
    ]
    for payload in bad:
        assert run(db, json.dumps(payload)).returncode != 0
        assert not db.exists()


def test_extra_fields_ignored_and_not_stored(tmp_path):
    db = tmp_path / "events.db"
    payload = {
        "session_id": "s1",
        "hook_event_name": "PostToolUse",
        "cwd": "/secret/place",
        "prompt": "free text here",
        "tool_input": {"file_path": "/x/y"},
    }
    assert run(db, json.dumps(payload)).returncode == 0
    with sqlite3.connect(db) as conn:
        cols = [c[1] for c in conn.execute("PRAGMA table_info(hook_events)")]
        dump = "\n".join(conn.iterdump())
    assert set(cols) == {"id", "session_id", "hook_event_name", "tool_name", "timestamp"}
    assert "/secret/place" not in dump and "free text" not in dump


def _load_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("hook_record", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_main_in_process(tmp_path, monkeypatch):
    import io

    mod = _load_module()
    db = tmp_path / "e.db"
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id":"a","hook_event_name":"Stop"}'))
    assert mod.main(["--db", str(db)]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("nope"))
    assert mod.main(["--db", str(tmp_path / "x.db")]) == 2
    assert not (tmp_path / "x.db").exists()
