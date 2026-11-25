import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from etat_major.cli import main
from test_planning_execution_links import _record as _links_record
from test_planning_execution_links import _row
from test_planning_manual_review import _record as _review_record
from test_planning_meute import _snapshot
from test_planning_web import client_for as client_for
from test_planning_web import planning_workspace as planning_workspace

MARKER = "etat-major/planning@1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs/contracts/schemas/planning.schema.json"


def _validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _errors(payload):
    return [f"{list(e.absolute_path)}: {e.message}" for e in _validator().iter_errors(payload)]


def test_schema_file_is_draft_2020_12_and_names_the_marker():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema"] == {"const": MARKER}


def test_demo_export_carries_marker_and_validates(workspace_dir, capsys):
    args = ["export", "planning", "--json", "--workspace", str(workspace_dir)]
    assert main([*args, "--project", "netlens"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == MARKER
    assert payload["version"] == 1
    assert _errors(payload) == []


def test_project_json_with_every_optional_section_validates(
    planning_workspace, client_for, tmp_path
):
    pytest.importorskip("fastapi")
    flags = (
        "--meute",
        _snapshot(tmp_path / "meute.yaml"),
        "--manual-review",
        _review_record(tmp_path / "manual.yaml"),
        "--execution-links",
        _links_record(tmp_path / "links.yaml", [_row()]),
    )
    with client_for(planning_workspace, *flags) as client:
        payload = client.get("/project.json").json()
    assert payload["schema"] == MARKER
    assert {"meute", "manual_review", "execution_links"} <= set(payload)
    assert _errors(payload) == []


def test_schema_rejects_unknown_task_state_and_missing_marker(workspace_dir, capsys):
    args = ["export", "planning", "--json", "--workspace", str(workspace_dir)]
    assert main([*args, "--project", "netlens"]) == 0
    payload = json.loads(capsys.readouterr().out)
    bad_state = {**payload, "tasks": [{**payload["tasks"][0], "state": "wip"}]}
    assert _errors(bad_state)
    assert _errors({k: v for k, v in payload.items() if k != "schema"})
