import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator

from etat_major.cli import main
from etat_major.discover_view import (
    DecisionRow,
    DiscoverView,
    FindingRow,
    ResearchRow,
    discover_payload,
)

MARKER = "etat-major/discover@1"
SRC = str(Path(__file__).parents[1] / "src")
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/contracts/schemas/discover.schema.json"


def _args(workspace, project="netlens"):
    return ["export", "discover", "--json", "--workspace", str(workspace), "--project", project]


def _errors(payload):
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return [
        f"{list(e.absolute_path)}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(payload)
    ]


def _export(workspace_dir, capsys):
    assert main(_args(workspace_dir)) == 0
    return capsys.readouterr().out


def test_payload_serializes_dates_and_is_json_dumpable():
    view = DiscoverView(
        (
            ResearchRow(
                "r1",
                "T",
                "unreviewed",
                "ai-generated",
                None,
                (FindingRow("f1", "x", "https://e.org", date(2026, 1, 2), False),),
                0,
                (),
            ),
        ),
        (DecisionRow("d1", "q", "proposed", date(2026, 3, 4), None, None, (), 0, (), 0, ()),),
    )
    payload = discover_payload(view)
    assert payload["schema"] == MARKER and payload["version"] == 1
    assert payload["research"][0]["findings"][0]["source_date"] == "2026-01-02"
    assert payload["decisions"][0]["decided_on"] == "2026-03-04"
    assert "has_data" not in payload
    json.dumps(payload)


def test_schema_file_is_closed_draft_2020_12_and_names_the_marker():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema"] == {"const": MARKER}
    assert schema["additionalProperties"] is False


def test_demo_export_validates_and_has_content(workspace_dir, capsys):
    payload = json.loads(_export(workspace_dir, capsys))
    assert payload["schema"] == MARKER
    assert payload["decisions"] or payload["research"]
    assert _errors(payload) == []


def test_schema_rejects_unknown_key_and_missing_marker(workspace_dir, capsys):
    payload = json.loads(_export(workspace_dir, capsys))
    assert _errors({**payload, "extra": 1})
    assert _errors({k: v for k, v in payload.items() if k != "schema"})
    assert _errors({**payload, "version": 2})


def test_export_is_deterministic_sorted_json(workspace_dir, capsys):
    first = _export(workspace_dir, capsys)
    assert _export(workspace_dir, capsys) == first
    assert first == json.dumps(json.loads(first), sort_keys=True, indent=2) + "\n"


def test_export_runs_without_web_packages(workspace_dir):
    code = (
        "import sys\n"
        "for name in ('fastapi', 'starlette', 'uvicorn', 'httpx'):\n"
        "    sys.modules[name] = None\n"
        f"sys.path.insert(0, {SRC!r})\n"
        "from etat_major.cli import main\n"
        f"sys.exit(main({_args(workspace_dir)!r}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["schema"] == MARKER


def test_export_errors_name_export_discover(workspace_dir, capsys):
    assert main(_args(workspace_dir, "nope")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "export discover: field 'project'" in captured.err
    assert "serve" not in captured.err and "export planning" not in captured.err


def test_export_requires_json_flag(workspace_dir, capsys):
    args = ["export", "discover", "--workspace", str(workspace_dir), "--project", "netlens"]
    try:
        main(args)
    except SystemExit as exc:
        assert exc.code == 2
    assert "--json" in capsys.readouterr().err
