import json
import tomllib
from pathlib import Path

import pytest

from etat_major import floorplan

FIXTURE = Path(__file__).parent / "fixtures" / "floorplan" / "plan.json"
PINS = Path(__file__).parents[1] / "pins.toml"


def test_tool_pins():
    pins = tomllib.loads(PINS.read_text())
    assert pins["floorplan"] == {
        "tag": "floorplan--v0.11.0",
        "commit": "94f81b463b7617e06d873ac71323ce71644c8399",
    }
    assert pins["trail"]["version"] == "0.30.5"


def test_recorded_blueprint_paths_are_immutable():
    plan = floorplan.load_plan(FIXTURE)
    assert plan.file_paths == frozenset(
        {"src/etat_major/wiring.py", "src/etat_major/repo_index.py", "tests/test_wiring.py"}
    )
    with pytest.raises(AttributeError):
        plan.file_paths = frozenset()


def write_plan(tmp_path, transform):
    data = json.loads(FIXTURE.read_text())
    transform(data)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("marker", [None, "schema"])
def test_legacy_and_schema_alias(tmp_path, marker):
    def transform(data):
        schema = data.pop("$schema")
        if marker:
            data[marker] = schema
        data["source"] = "/private/blueprint"
        data["meta"] = {"remote": "git@example.invalid:repo"}
        data["files"][0]["description"] = "Built at /private/path"

    plan = floorplan.load_plan(write_plan(tmp_path, transform))
    assert "private" not in repr(plan)
    assert "example.invalid" not in repr(plan)
    assert len(plan.file_paths) == 3


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"$schema": "floorplan/plan@2"}, "schema"),
        ({"schema": None}, "schema"),
        ({"source": {}}, "source"),
        ({"stack": [1]}, "stack.0"),
        ({"assumptions": {}}, "assumptions"),
        ({"questions": ["bad"]}, "questions.0"),
        ({"endpoints": {}}, "endpoints"),
        (
            {"files": [{"path": "/private/file.py", "name": "bad", "description": "bad"}]},
            "files.0.path",
        ),
        ({"files": [{"path": "ok.py", "name": [], "description": "bad"}]}, "files.0.name"),
    ],
)
def test_plan_reports_failing_field(tmp_path, changes, field):
    path = write_plan(tmp_path, lambda data: data.update(changes))
    with pytest.raises(floorplan.FloorplanError) as exc:
        floorplan.load_plan(path)
    assert "plan.json" in str(exc.value) and field in str(exc.value)
    assert "/private" not in str(exc.value)


@pytest.mark.parametrize("payload", ["[]", "{bad", '{"files": NaN}'])
def test_plan_rejects_invalid_json_input(tmp_path, payload):
    path = tmp_path / "plan.json"
    path.write_text(payload)
    with pytest.raises(floorplan.FloorplanError, match=r"plan.json.*JSON"):
        floorplan.load_plan(path)


def test_plan_rejects_symlink_parent(tmp_path):
    directory = tmp_path / "alias"
    directory.symlink_to(FIXTURE.parent, target_is_directory=True)
    with pytest.raises(floorplan.FloorplanError, match=r"plan.json.*cannot read"):
        floorplan.load_plan(directory / "plan.json")


def test_plan_rejects_oversized_file(tmp_path):
    path = tmp_path / "plan.json"
    with path.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(floorplan.FloorplanError, match=r"plan.json.*64 MiB"):
        floorplan.load_plan(path)
