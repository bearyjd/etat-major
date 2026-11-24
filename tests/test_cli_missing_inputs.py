import json
from pathlib import Path

import pytest

from etat_major.cli import main
from test_components_cli import component_workspace as component_workspace

FIXTURES = Path(__file__).parent / "fixtures"
GRAPH = FIXTURES / "floorplan/graph-real.json"
TRAIL = FIXTURES / "trail/wiring-kotlin.json"


def run(capsys, argv):
    status = main(argv)
    return status, capsys.readouterr()


@pytest.mark.parametrize("missing", ["graph", "trail", "both"])
@pytest.mark.parametrize("fmt", ["text", "json"])
def test_index_names_missing_input_without_traceback(tmp_path, capsys, missing, fmt):
    graph = tmp_path / "absent-graph.json" if missing in ("graph", "both") else GRAPH
    trail = tmp_path / "absent-trail.json" if missing in ("trail", "both") else TRAIL
    status, out = run(
        capsys, ["index", "--graph", str(graph), "--trail", str(trail), "--format", fmt]
    )
    assert status == 2
    assert "Traceback" not in out.err + out.out
    named = "absent-graph.json" if missing != "trail" else "absent-trail.json"
    text = out.err if fmt == "text" else json.dumps(json.loads(out.out)["issues"])
    assert named in text
    assert str(tmp_path) not in out.out


def test_index_with_both_inputs_reports_coverage_fields(capsys):
    status, out = run(
        capsys,
        ["index", "--graph", str(GRAPH), "--trail", str(TRAIL), "--format", "json"],
    )
    assert status == 0
    coverage = json.loads(out.out)["data"]["coverage"]
    assert "architecture_only" in coverage and "symbols_only" in coverage


def test_components_coverage_names_missing_graph(component_workspace, tmp_path, capsys):
    argv = ["components", "coverage", "--workspace", str(component_workspace)]
    argv += ["--project", "netlens", "--graph", str(tmp_path / "absent-graph.json")]
    status, out = run(capsys, argv)
    assert status == 2
    assert "absent-graph.json" in out.err
    assert "Traceback" not in out.err + out.out


def test_components_map_does_not_need_recordings(component_workspace, capsys):
    argv = ["components", "map", "--workspace", str(component_workspace)]
    status, out = run(capsys, [*argv, "--project", "netlens", "--path", "app/a.kt"])
    assert status == 0
    assert "client.app" in out.out
