import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from etat_major.cli import main
from test_progress import History

FIXTURE = Path(__file__).parent / "fixtures" / "meute" / "explicit-task.json"
TASK = "netlens/0042"
REF = "reports/example/scan-2026-11-21.md"
SCHEMA = Path(__file__).parents[1] / "docs/contracts/schemas/progress.schema.json"


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "meute.json"
    snapshot = json.loads(FIXTURE.read_text())
    History.write(path, snapshot)
    return path, snapshot


@pytest.fixture
def history(tmp_path):
    return History(tmp_path)


def run_progress(history, capsys, path, *, expected=0):
    status = main([*history.args(), "--meute", str(path)])
    out = capsys.readouterr()
    assert status == expected, out.err or out.out
    assert "Traceback" not in out.err
    assert str(path.parent) not in out.out + out.err
    return json.loads(out.out)


def test_meute_progress_only_adds_generated_proof(history, capsys, recording):
    path, _ = recording
    baseline = history.report(capsys)
    assert "meute" not in baseline
    result = run_progress(history, capsys, path)
    assert result["schema"] == "etat-major/progress@1"
    data = result["data"]
    assert data.pop("meute") == {
        "version": 1,
        "project": "netlens",
        "exported_at": "2026-11-22T12:00:00Z",
        "reports": [
            {
                "ref": REF,
                "recorded_at": "2026-11-21T12:00:00Z",
                "outcome": "ok",
                "task": TASK,
                "linked": True,
            }
        ],
    }
    baseline["tasks"][TASK]["generated"] = [f"artifact:{REF}"]
    assert data == baseline


def test_meute_progress_json_matches_existing_versioned_schema(history, capsys, recording):
    path, _ = recording
    result = run_progress(history, capsys, path)
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)


def test_meute_progress_keeps_recorded_metadata_without_attribution(history, capsys):
    path = history.workspace.parent / "recorded-unlinked.yaml"
    path.write_bytes(FIXTURE.with_name(path.name).read_bytes())
    data = run_progress(history, capsys, path)["data"]
    assert data["meute"]["reports"] == [
        {
            "ref": "reports/example/scan-2026-11-17.md",
            "recorded_at": "2026-11-17T07:19:40-05:00",
            "outcome": "ok",
            "task": None,
            "linked": False,
        }
    ]
    assert data["tasks"][TASK]["generated"] == "unverified"


@pytest.mark.parametrize("task", [None, "netlens/9999", "other/0042"])
def test_meute_progress_retains_rows_without_matching_task(history, capsys, recording, task):
    path, snapshot = recording
    row = snapshot["reports"][0]
    if task is None:
        del row["task"]
    else:
        row["task"] = task
    history.record(
        "tasks/other/0042-latency.md",
        "id: '0042'\nproject: other\ntitle: Other\ninitiative: network\n"
        "owner: maintainer\nstatus: ready",
    )
    history.write(path, snapshot)
    data = run_progress(history, capsys, path)["data"]
    assert data["meute"]["reports"] == [row | {"task": task, "linked": False}]
    assert {key: task["generated"] for key, task in data["tasks"].items()} == {
        TASK: "unverified",
        "other/0042": "unverified",
    }


def test_meute_progress_deduplicates_and_is_read_only(history, capsys, recording):
    path, snapshot = recording
    snapshot["reports"] *= 2
    history.write(path, snapshot)
    artifacts = (path, history.prs, history.releases, *history.workspace.rglob("*.md"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in artifacts}
    first = run_progress(history, capsys, path)
    assert run_progress(history, capsys, path) == first
    data = first["data"]
    assert data["tasks"][TASK]["generated"] == [f"artifact:{REF}"]
    assert len(data["meute"]["reports"]) == 1
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in artifacts} == before


def test_meute_progress_text_labels_old_capture_and_report_times(history, capsys, recording):
    path, snapshot = recording
    snapshot["exported_at"] = "2024-11-22T12:00:00Z"
    snapshot["reports"][0]["recorded_at"] = "2024-11-21T12:00:00Z"
    history.write(path, snapshot)
    assert main([*history.args("text"), "--meute", str(path)]) == 0
    out = capsys.readouterr().out
    assert f"artifact:{REF}" in out
    assert "Meute snapshot" in out
    assert "2024-11-22T12:00:00Z" in out
    assert "2024-11-21T12:00:00Z" in out


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 2),
        ("version", True),
        ("project", "../other"),
        ("exported_at", "2026-11-22T12:00:00"),
        ("exported_at", "1234567890"),
        ("reports", [{}] * 257),
        ("reports.0.recorded_at", "2026-11-23T12:00:00Z"),
        ("reports.0.recorded_at", 1234567890),
        ("reports.0.task", "netlens/*"),
        ("reports.0.outcome", "private\ntext"),
        ("reports.0.ref", "/private/report.md"),
        ("reports.0.ref", "reports/../report.md"),
        ("reports.0.ref", "reports//report.md"),
        ("reports.0.ref", "https://external.invalid/report.md"),
        ("reports.0.ref", "private@external.invalid:report.md"),
        ("reports.0.ref", "reports\\report.md"),
        ("reports.0.ref", "reports/report.md?token=secret"),
        ("reports.0.ref", "reports/report\u2028.md"),
    ],
)
def test_meute_progress_rejects_invalid_fields(history, capsys, recording, field, value):
    path, snapshot = recording
    row = snapshot["reports"][0] if field.startswith("reports.0.") else snapshot
    row[field.split(".")[-1]] = value
    history.write(path, snapshot)
    error = run_progress(history, capsys, path, expected=2)
    assert error["data"] is None
    assert [(e["path"], e["field"]) for e in error["issues"]] == [(path.name, field)]
    assert "private" not in json.dumps(error)


@pytest.mark.parametrize(
    "change", [{"task": "netlens/9999"}, {"recorded_at": "2026-11-21T07:00:00-05:00"}]
)
def test_meute_progress_rejects_conflicting_rows_for_same_ref(history, capsys, recording, change):
    path, snapshot = recording
    snapshot["reports"].append(snapshot["reports"][0] | change)
    history.write(path, snapshot)
    error = run_progress(history, capsys, path, expected=2)
    assert error["issues"][0]["field"] == "reports.1.ref"


@pytest.mark.parametrize("problem", ["absent", "symlink", "parent", "large", "encoding"])
def test_meute_progress_rejects_unreadable_input(history, capsys, recording, problem):
    path, _ = recording
    if problem == "absent":
        path.unlink()
    elif problem == "symlink":
        target = path.rename(path.with_suffix(".data"))
        path.symlink_to(target)
    elif problem == "parent":
        real = path.parent / "real"
        real.mkdir()
        path.rename(real / path.name)
        alias = path.parent / "alias"
        alias.symlink_to(real, target_is_directory=True)
        path = alias / path.name
    elif problem == "large":
        path.write_bytes(b" " * (256 * 1024 + 1))
    else:
        path.write_bytes(b"\xff")
    error = run_progress(history, capsys, path, expected=2)
    assert [(e["path"], e["field"]) for e in error["issues"]] == [(path.name, "file")]


@pytest.mark.parametrize(
    "raw",
    ["{", '{"version": 1, "version": 2}', "[" * 40 + "]" * 40, r'key: "\UFFFFFFFF"'],
)
def test_meute_progress_rejects_bad_mapping(history, capsys, recording, raw):
    path, _ = recording
    path.write_text(raw)
    error = run_progress(history, capsys, path, expected=2)
    assert error["issues"][0]["path"] == path.name
    assert error["issues"][0]["field"] in {"snapshot", "version"}


def test_meute_progress_requires_report_rows_in_a_sequence(history, capsys, recording):
    path, snapshot = recording
    path.write_text(json.dumps(snapshot).replace(json.dumps(snapshot["reports"]), "!!set {}"))
    error = run_progress(history, capsys, path, expected=2)
    assert error["issues"][0]["field"] == "reports"


@pytest.mark.parametrize("repeat", [1, 2])
def test_meute_progress_does_not_echo_unknown_keys(history, capsys, recording, repeat):
    path, snapshot = recording
    key = "reports.202641862.ref"
    # Repeat a fabricated field to exercise both model validation and YAML duplicate checks.
    path.write_text(json.dumps(snapshot)[:-1] + (f', "{key}": "unused"') * repeat + "}")
    error = run_progress(history, capsys, path, expected=2)
    assert error["issues"][0]["field"] == "snapshot"
    assert key not in json.dumps(error)
