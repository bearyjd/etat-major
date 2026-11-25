import json
import subprocess
import sys
from pathlib import Path

import pytest

from etat_major.cli import main

PROJECT = "netlens"
SRC = str(Path(__file__).parents[1] / "src")


def export_args(workspace, *extra):
    return [
        "export",
        "planning",
        "--json",
        "--workspace",
        str(workspace),
        "--project",
        PROJECT,
        *extra,
    ]


def test_export_planning_prints_deterministic_sorted_json(workspace_dir, capsys):
    assert main(export_args(workspace_dir)) == 0
    first = capsys.readouterr().out
    assert main(export_args(workspace_dir)) == 0
    assert capsys.readouterr().out == first
    payload = json.loads(first)
    assert first == json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert {"project", "features", "components", "tasks", "sources", "issues", "version"} <= set(
        payload
    )
    assert "_understand" not in payload and "_discover" not in payload


def test_export_requires_json_flag(workspace_dir, capsys):
    args = ["export", "planning", "--workspace", str(workspace_dir), "--project", PROJECT]
    with pytest.raises(SystemExit) as exit_info:
        main(args)
    assert exit_info.value.code == 2
    assert "--json" in capsys.readouterr().err


def test_export_reports_file_and_field_error_without_traceback(tmp_path, capsys):
    assert main(export_args(tmp_path / "missing")) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert captured.err.startswith("error") or "field" in captured.err


def test_export_matches_project_json_route(workspace_dir, capsys, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    import uvicorn
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(app))
    serve = ["serve", "--workspace", str(workspace_dir), "--project", PROJECT, "--port", "8117"]
    assert main(serve) == 0
    capsys.readouterr()
    assert main(export_args(workspace_dir)) == 0
    exported = json.loads(capsys.readouterr().out)
    with TestClient(calls[0], base_url="http://127.0.0.1:8117") as client:
        assert client.get("/project.json").json() == exported


def test_export_runs_without_web_packages(workspace_dir):
    code = (
        "import sys\n"
        "for name in ('fastapi', 'starlette', 'uvicorn', 'httpx'):\n"
        "    sys.modules[name] = None\n"
        f"sys.path.insert(0, {SRC!r})\n"
        "from etat_major.cli import main\n"
        f"sys.exit(main({export_args(workspace_dir)!r}))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["project"]


def test_export_errors_name_export_not_serve(workspace_dir, capsys):
    args = export_args(workspace_dir)
    args[args.index(PROJECT)] = "nope"
    assert main(args) == 2
    error = capsys.readouterr().err
    assert "export planning: field 'project'" in error
    assert "serve" not in error
