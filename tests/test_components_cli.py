import json
from pathlib import Path
from shutil import copytree

import pytest
from jsonschema import Draft202012Validator

from etat_major.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMAS = Path(__file__).parents[1] / "docs/contracts/schemas"
GRAPH = FIXTURES / "floorplan/graph-real.json"


@pytest.fixture
def component_workspace(tmp_path):
    directory = tmp_path / "components"
    directory.mkdir()
    (directory / "netlens.yaml").write_text(
        """version: 1
project: netlens
components:
  - id: client
    label: Client
    kind: grouping
    paths: []
  - id: client.app
    label: Application
    kind: android
    parent: client
    paths: [app]
""",
        encoding="utf-8",
    )
    return tmp_path


def result(capsys, action, args, status=0):
    assert main(["components", action, *args, "--format", "json"]) == status
    output = capsys.readouterr()
    assert not output.err
    value = json.loads(output.out)
    assert value["schema"] == f"etat-major/components-{action}@1"
    assert value["ok"] is (status == 0)
    assert output.out == json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    schema = json.loads((SCHEMAS / f"components-{action}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)
    return value


@pytest.mark.parametrize("action", ["validate", "map", "coverage", "seed"])
def test_argument_errors_use_action_schema(capsys, action):
    error = result(capsys, action, [], 2)
    assert error["data"] is None
    assert error["issues"][0]["field"] == "arguments"


def test_validate_returns_all_file_errors(component_workspace, capsys):
    workspace = ["--workspace", str(component_workspace)]
    assert result(capsys, "validate", workspace)["data"] == {}
    for filename in ("one.yaml", "two.yaml"):
        (component_workspace / "components" / filename).write_text("[]", encoding="utf-8")
    errors = result(capsys, "validate", workspace, 1)["issues"]
    assert [issue["path"] for issue in errors] == ["components/one.yaml", "components/two.yaml"]
    assert all(issue["field"] for issue in errors)


def test_validate_text_prints_success(component_workspace, capsys):
    assert main(["components", "validate", "--workspace", str(component_workspace)]) == 0
    output = capsys.readouterr()
    assert output.out == "ok\n"
    assert not output.err


def test_map_reports_component_and_ancestor_ids(component_workspace, capsys):
    path = "app/src/main/kotlin/example/App.kt"
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--path", path]
    assert result(capsys, "map", args)["data"] == {
        "project": "netlens",
        "path": path,
        "component": "client.app",
        "ancestors": ["client"],
        "ties": [],
    }
    assert result(capsys, "map", args) == result(capsys, "map", args)
    assert main(["components", "map", *args, "--format", "text"]) == 0
    assert "client.app" in capsys.readouterr().out


def test_map_reports_ties_without_picking_an_owner(component_workspace, capsys):
    model = component_workspace / "components/netlens.yaml"
    with model.open("a", encoding="utf-8") as stream:
        stream.write("  - {id: other, label: Other, kind: app, paths: [app]}\n")
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--path", "app/a.kt"]
    value = result(capsys, "map", args)
    assert value["data"]["component"] is None
    assert value["data"]["ties"] == ["client.app", "other"]
    assert value["issues"][0]["severity"] == "warning"


def test_map_returns_unowned_path_as_a_successful_query(component_workspace, capsys):
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--path", "other.kt"]
    assert result(capsys, "map", args)["data"]["component"] is None


@pytest.mark.parametrize(
    ("project", "path", "field"),
    [("unknown", "app/a.kt", "project"), ("netlens", "/private/hidden", "path")],
)
def test_map_rejects_invalid_inputs(component_workspace, capsys, project, path, field):
    args = ["--workspace", str(component_workspace), "--project", project, "--path", path]
    value = result(capsys, "map", args, 2)
    assert value["data"] is None
    assert value["issues"][0]["field"] == field
    assert "/private/hidden" not in json.dumps(value)


def test_coverage_uses_recorded_floorplan_files(component_workspace, capsys):
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--graph", str(GRAPH)]
    data = result(capsys, "coverage", args)["data"]
    assert len(data["owned"]) == 13
    assert len(data["unowned"]) == 157
    assert data["owned"][0] == "app/build.gradle.kts"
    assert data["unowned"][0] == ".trail/hook.cjs"
    assert data["percentage"] == pytest.approx(13 / 170 * 100)
    assert main(["components", "coverage", *args, "--format", "text"]) == 0
    assert "app/build.gradle.kts" in capsys.readouterr().out


def test_coverage_rejects_malformed_floorplan_input(component_workspace, capsys):
    graph = component_workspace / "malformed.json"
    graph.write_text("[", encoding="utf-8")
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--graph", str(graph)]
    value = result(capsys, "coverage", args, 2)
    assert value["issues"][0]["path"] == "malformed.json"
    assert value["issues"][0]["field"] == "JSON"


def test_seed_reports_created_file_and_refuses_existing_destination(tmp_path, capsys):
    repo = tmp_path / "repo"
    copytree(FIXTURES / "gradle-real", repo)
    out = tmp_path / "netlens.yaml"
    args = ["--root", str(repo), "--project", "netlens", "--out", str(out)]
    value = result(capsys, "seed", args)
    assert value["data"]["output"] == "netlens.yaml"
    assert value["data"]["project"] == "netlens"
    assert "feature.portscan" in value["data"]["components"]
    original = out.read_bytes()
    assert out.is_file()
    error = result(capsys, "seed", args, 2)
    assert "exists" in error["issues"][0]["message"]
    assert out.read_bytes() == original
    second = tmp_path / "second.yaml"
    assert (
        main(
            [
                "components",
                "seed",
                "--root",
                str(repo),
                "--project",
                "netlens",
                "--out",
                str(second),
                "--format",
                "text",
            ]
        )
        == 0
    )
    assert "second.yaml" in capsys.readouterr().out
    assert second.read_bytes() == original


def test_seed_proposal_flag_creates_sibling_file(component_workspace, capsys):
    repo = component_workspace / "repo"
    copytree(FIXTURES / "gradle-real", repo)
    existing = component_workspace / "components/netlens.yaml"
    original = existing.read_bytes()
    args = [
        "--root",
        str(repo),
        "--project",
        "netlens",
        "--trail",
        str(FIXTURES / "trail/wiring-kotlin.json"),
        "--proposal-for",
        str(existing),
    ]
    value = result(capsys, "seed", args)
    assert value["data"]["output"] == "netlens.yaml.proposed"
    assert "feature.portscan" in value["data"]["components"]
    assert existing.read_bytes() == original
    assert existing.with_name("netlens.yaml.proposed").is_file()


def test_coverage_tied_files_are_unowned_and_have_diagnostics(component_workspace, capsys):
    model = component_workspace / "components/netlens.yaml"
    with model.open("a", encoding="utf-8") as stream:
        stream.write("  - {id: other, label: Other, kind: app, paths: [app]}\n")
    args = [
        "--workspace",
        str(component_workspace),
        "--project",
        "netlens",
        "--graph",
        str(FIXTURES / "floorplan/graph.json"),
    ]
    value = result(capsys, "coverage", args)
    assert value["data"]["owned"] == []
    assert value["data"]["percentage"] == 0
    assert len(value["data"]["unowned"]) == 2
    assert all(issue["severity"] == "warning" for issue in value["issues"])
    assert any(
        "client.app" in issue["message"] and "other" in issue["message"]
        for issue in value["issues"]
    )


def test_coverage_rejects_unsafe_paths_without_echoing_them(component_workspace, capsys):
    graph = component_workspace / "hostile.json"
    source = json.loads((FIXTURES / "floorplan/graph.json").read_text(encoding="utf-8"))
    source["files"][0]["p"] = "app/hidden\x1bname.kt"
    graph.write_text(json.dumps(source), encoding="utf-8")
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--graph", str(graph)]
    value = result(capsys, "coverage", args, 2)
    assert value["issues"][0]["path"] == "hostile.json"
    assert value["issues"][0]["field"] == "files"
    assert "hidden" not in json.dumps(value)


def test_seed_output_options_are_mutually_exclusive(tmp_path, capsys):
    args = [
        "--root",
        str(tmp_path),
        "--project",
        "netlens",
        "--out",
        str(tmp_path / "new.yaml"),
        "--proposal-for",
        str(tmp_path / "existing.yaml"),
    ]
    assert result(capsys, "seed", args, 2)["issues"][0]["field"] == "arguments"


@pytest.mark.parametrize("path", ["app/src/App Home.kt", "app/-/Home.kt"])
def test_map_preserves_literal_repository_file(component_workspace, capsys, path):
    args = [
        "--workspace",
        str(component_workspace),
        "--project",
        "netlens",
        "--path",
        path,
    ]
    value = result(capsys, "map", args)
    assert value["data"]["path"] == path
    assert value["data"]["component"] == "client.app"


def test_coverage_accepts_spaces_in_recorded_repository_files(component_workspace, capsys):
    graph = component_workspace / "spaces.json"
    source = json.loads((FIXTURES / "floorplan/graph.json").read_text(encoding="utf-8"))
    source["files"][0]["p"] = "app/src/App Home.kt"
    graph.write_text(json.dumps(source), encoding="utf-8")
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--graph", str(graph)]
    value = result(capsys, "coverage", args)
    assert "app/src/App Home.kt" in value["data"]["owned"]


@pytest.mark.parametrize("name", ["100%.kt", "tag#1.kt", "tag:1.kt"])
def test_coverage_retains_nonmatchable_relative_recorded_paths(component_workspace, capsys, name):
    graph = component_workspace / "recorded.json"
    source = json.loads((FIXTURES / "floorplan/graph.json").read_text(encoding="utf-8"))
    path = f"app/src/{name}"
    source["files"][0]["p"] = path
    graph.write_text(json.dumps(source), encoding="utf-8")
    args = ["--workspace", str(component_workspace), "--project", "netlens", "--graph", str(graph)]
    value = result(capsys, "coverage", args)
    assert value["data"]["unowned"] == [path]
    assert value["data"]["percentage"] == 50
    assert value["issues"][0]["severity"] == "warning"
    assert path not in value["issues"][0]["message"]
