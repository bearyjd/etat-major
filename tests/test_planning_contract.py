import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from etat_major import planning
from etat_major.workspace import load_workspace

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("fields", "valid"),
    [
        ({"milestone": "m3", "depends_on": ["0041", 40], "targets": ["fp:n:ui"]}, True),
        ({"depends_on": ["task:netlens/0041"]}, False),
        ({"targets": ["feature:netlens/0031"]}, False),
        ({"targets": ["fp:f:/private/hidden.py"]}, False),
        ({"budget_tokens": 200}, False),
        ({"status": "in-progress"}, False),
        ({"accepted_by": "maintainer"}, False),
        ({"accepted_on": "2027-03-01"}, False),
        ({"status": "done"}, False),
        ({"status": "done", "accepted_by": "maintainer"}, False),
        ({"status": "done", "accepted_on": "2027-03-01"}, False),
        ({"status": "done", "accepted_by": " ", "accepted_on": "2027-03-01"}, False),
        ({"status": "done", "accepted_by": "maintainer", "accepted_on": "2027-02-30"}, False),
        ({"status": "done", "accepted_by": "maintainer", "accepted_on": "2027-03-01"}, True),
    ],
)
def test_task_schema_matches_planning_contract(fields, valid):
    schema = json.loads((ROOT / "docs/contracts/task-file.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    frontmatter = {
        "id": "0042",
        "title": "Latency",
        "initiative": "i",
        "project": "netlens",
        "owner": "maintainer",
        "status": "ready",
        **fields,
    }
    assert validator.is_valid(frontmatter) is valid


def test_demo_planning_files_form_a_board(workspace_dir):
    ws = load_workspace(workspace_dir)
    assert ws.issues == ()
    vision = planning.parse_vision(workspace_dir / "visions/netlens.md")
    milestone = planning.parse_milestone(workspace_dir / "milestones/netlens/m3-latency.md")
    assert vision.project == "netlens"
    assert milestone.horizon == "now"
    assert [(task.id, task.milestone) for task in ws.tasks] == [("0041", "m3"), ("0042", "m3")]
    states = {task.id: task.status for task in ws.tasks}
    assert [planning.derive_board_column(task, states) for task in ws.tasks] == ["done", "ready"]
