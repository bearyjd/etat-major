import json
import tomllib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pydantic import ValidationError

from etat_major import repo_index
from etat_major.cli import main
from etat_major.trail import TrailError

FIXTURES = Path(__file__).parent / "fixtures"
GRAPH = FIXTURES / "repo-index" / "graph.json"
TRAIL = FIXTURES / "trail" / "wiring.json"
TASKFILE = "src/etat_major/taskfile.py"


def test_snapshot_joins_by_file_path_and_keeps_provenance():
    index = repo_index.load_repo_index(GRAPH, TRAIL)
    assert index.repository == "etat-major"
    assert index.revision is None
    assert index.indexed_at is None
    assert [(item.layer, item.name) for item in index.indexers] == [
        ("architecture", "floorplan"),
        ("symbols", "trail"),
    ]
    assert [file.path for file in index.files_with_symbols()] == [TASKFILE]
    assert index.component_of(TASKFILE).id == "validation"
    assert index.component_of(TASKFILE).provenance == "inferred"
    assert index.component_of("unknown.py") is None
    symbols = index.symbols_for_component("validation")
    assert {symbol.path for symbol in symbols} == {TASKFILE}
    assert any(symbol.id == TASKFILE + "#parse_task" for symbol in symbols)
    assert all(symbol.kind != "file" for symbol in symbols)
    assert {(symbol.layer, symbol.provenance) for symbol in symbols} == {("symbols", "verified")}
    assert index.symbols_for_component("future") == ()
    assert index.symbols_for_component("unknown") == ()
    assert index.architecture.files[0].layer == "architecture"
    assert [(link.kind, link.provenance) for link in index.architecture.links] == [
        ("import", "inferred"),
        ("http", "inferred"),
    ]
    assert index.architecture.routes[0].path == "/health"
    assert any(edge.relation == "calls" for edge in index.symbols.edges)
    assert any(edge.relation == "extends" for edge in index.symbols.edges)
    with pytest.raises(FrozenInstanceError):
        index.repository = "other"
    with pytest.raises(ValidationError, match="frozen"):
        index.architecture.files[0].path = "other.py"


def test_coverage_and_directory_imports():
    index = repo_index.load_repo_index(GRAPH, TRAIL)
    coverage = index.coverage
    assert coverage.architecture_only == ("app/entry.py",)
    assert coverage.symbols_only == (
        "src/etat_major/__init__.py",
        "tests/test_repo_hygiene.py",
        "tests/test_smoke.py",
        "tests/test_taskfile.py",
    )
    assert coverage.languages == ("python",)
    assert coverage.files_indexed == 6
    assert coverage.files_skipped is None
    assert [(node.path, node.imports) for node in index.architecture.modules] == [
        ("app", ("src/etat_major",)),
        ("src/etat_major", ()),
    ]
    assert {(node.layer, node.provenance) for node in index.architecture.modules} == {
        ("architecture", "inferred")
    }


def test_original_slice_one_graph_has_no_shared_paths():
    index = repo_index.load_repo_index(FIXTURES / "floorplan" / "graph.json", TRAIL)
    assert index.repository == "netlens"
    assert not index.files_with_symbols()
    assert len(index.coverage.architecture_only) == 2
    assert len(index.coverage.symbols_only) == 5


def test_indexer_metadata_describes_maintained_adapter_pins():
    pins_path = FIXTURES.parents[1] / "pins.toml"
    pins = tomllib.loads(pins_path.read_text())
    floorplan, trail = repo_index.load_repo_index(GRAPH, TRAIL).indexers
    assert floorplan.commit == pins["floorplan"]["commit"]
    assert trail.version == pins["trail"]["version"]
    assert {floorplan.provenance, trail.provenance} == {"human"}


def test_index_cli_json_is_stable_when_input_arrays_are_reordered(tmp_path, capsys):
    graph = json.loads(GRAPH.read_text())
    trail = json.loads(TRAIL.read_text())
    graph_path, trail_path = tmp_path / "graph.json", tmp_path / "wiring.json"
    args = ["index", "--graph", str(graph_path), "--trail", str(trail_path), "--format", "json"]
    graph_path.write_text(json.dumps(graph))
    trail_path.write_text(json.dumps(trail))
    assert main(args) == 0
    baseline = capsys.readouterr().out
    for key in ("files", "links", "nodes", "routes"):
        graph[key].reverse()
    for key in ("nodes", "edges"):
        trail[key].reverse()
    graph_path.write_text(json.dumps(graph))
    trail_path.write_text(json.dumps(trail))
    assert main(args) == 0
    assert capsys.readouterr().out == baseline
    view = json.loads(baseline)["data"]
    assert view["version"] == 1
    assert [entry["id"] for entry in view["architecture"]["components"]] == ["future", "validation"]
    assert view["symbols"]["nodes"][0]["range"] == [1, 4]
    assert view["symbols"]["nodes"][0]["layer"] == "symbols"
    assert any(
        edge["relation"] == "calls"
        and edge["confidence"] == "extracted"
        and edge["provenance"] == "verified"
        and edge["from"]
        and edge["to"]
        for edge in view["symbols"]["edges"]
    )


def test_index_cli_text_and_json_do_not_export_artifact_metadata(tmp_path, capsys):
    data = json.loads(GRAPH.read_text())
    hidden = tmp_path / "hidden"
    remote = f"ssh://{tmp_path.name}/hidden"
    data["meta"] = {"root": str(hidden), "remote": remote}
    data["nodes"][0]["summary"] = str(hidden)
    data["links"].append({"a": "f:app/entry.py", "b": remote, "k": "external"})
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(data))
    args = ["index", "--graph", str(graph), "--trail", str(TRAIL)]
    for extra in ([], ["--format", "json"]):
        assert main(args + extra) == 0
        output = capsys.readouterr().out
        assert str(hidden) not in output
        assert remote not in output
        assert "app/entry.py" in output


def test_index_cli_rejects_unsafe_trail_fields_without_echoing_them(tmp_path, capsys):
    data = json.loads(TRAIL.read_text())
    hidden = tmp_path / "hidden"
    data["edges"][0]["target"] = str(hidden)
    trail = tmp_path / "wiring.json"
    trail.write_text(json.dumps(data))
    with pytest.raises(TrailError, match=r"wiring.json.*edges\[0\]\.target"):
        repo_index.load_repo_index(GRAPH, trail)
    assert main(["index", "--graph", str(GRAPH), "--trail", str(trail)]) == 2
    error = capsys.readouterr().err
    assert "wiring.json" in error and "edges[0].target" in error
    assert str(hidden) not in error
    assert "Traceback" not in error


@pytest.mark.parametrize("unsafe", ["symlink", "linked-directory", "oversize", "invalid", "remote"])
def test_index_cli_reports_unsafe_or_invalid_input(tmp_path, capsys, unsafe):
    graph = tmp_path / "bad\u202e.json"
    field = "JSON"
    if unsafe == "symlink":
        graph.symlink_to(GRAPH)
    elif unsafe == "linked-directory":
        link = tmp_path / "link"
        link.symlink_to(GRAPH.parent, target_is_directory=True)
        graph = link / GRAPH.name
    elif unsafe == "oversize":
        with graph.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024 + 1)
    else:
        data = json.loads(GRAPH.read_text())
        hidden = (
            f"git@{tmp_path.name}:repo/hidden" if unsafe == "remote" else str(tmp_path / "hidden")
        )
        data["files"][0]["p"] = hidden
        graph.write_text(json.dumps(data))
        field = "files.0.p"
    assert main(["index", "--graph", str(graph), "--trail", str(TRAIL)]) == 2
    error = capsys.readouterr().err
    assert field in error and graph.name.replace("\u202e", r"\u202e") in error
    assert "\u202e" not in error and str(tmp_path) not in error and "Traceback" not in error
    if unsafe in {"remote", "invalid"}:
        assert hidden not in error


def test_repo_index_accepts_explicit_snapshot_metadata():
    index = repo_index.load_repo_index(
        GRAPH, TRAIL, revision="a" * 40, indexed_at="2026-11-21T12:00:00Z"
    )
    assert index.revision == "a" * 40
    assert index.indexed_at == "2026-11-21T12:00:00Z"


@pytest.mark.parametrize("metadata", [{"revision": "HEAD"}, {"indexed_at": "yesterday"}])
def test_invalid_snapshot_metadata_has_field_and_file(metadata):
    with pytest.raises(ValueError, match=rf"graph.json.*{next(iter(metadata))}"):
        repo_index.load_repo_index(GRAPH, TRAIL, **metadata)


def test_cli_can_export_caller_supplied_pair_metadata(capsys):
    args = ["index", "--graph", str(GRAPH), "--trail", str(TRAIL), "--format", "json"]
    assert main(args + ["--revision", "a" * 40, "--indexed-at", "2026-11-21T13:00:00+01:00"]) == 0
    output = json.loads(capsys.readouterr().out)["data"]
    assert output["revision"] == "a" * 40
    assert output["indexed_at"] == "2026-11-21T12:00:00Z"
    assert main(args + ["--revision", "HEAD"]) == 2
    assert json.loads(capsys.readouterr().out)["issues"][0]["field"] == "revision"


def test_json_keeps_identifiers_and_new_safe_trail_labels(tmp_path):
    graph = json.loads(GRAPH.read_text())
    trail = json.loads(TRAIL.read_text())
    path = "app/\ue000.py"
    symbol_id = path + "#overload[]"
    graph["files"].append({"p": path, "n": "future"})
    trail["nodes"].append({"id": symbol_id, "kind": "method", "path": path, "span": "L1-L1"})
    trail["edges"].append(
        {
            "source": symbol_id,
            "target": "external",
            "relation": "new relation",
            "confidence": "Plugin (experimental)",
        }
    )
    graph_path, trail_path = tmp_path / "graph.json", tmp_path / "wiring.json"
    graph_path.write_text(json.dumps(graph))
    trail_path.write_text(json.dumps(trail))
    index = repo_index.load_repo_index(graph_path, trail_path)
    exported = index.to_json()
    assert "\ue000" not in exported and r"\ue000" in exported
    output = json.loads(exported)
    assert any(node["id"] == symbol_id for node in output["symbols"]["nodes"])
    assert {
        "from": symbol_id,
        "to": "external",
        "relation": "new relation",
        "confidence": "Plugin (experimental)",
        "layer": "symbols",
        "provenance": "inferred",
    } in output["symbols"]["edges"]


def test_repeated_trail_id_with_tied_ranges_exports_stably(tmp_path):
    trail = json.loads(TRAIL.read_text())
    node = next(node for node in trail["nodes"] if node["kind"] == "function")
    trail["nodes"].append(dict(node, kind="method"))
    path = tmp_path / "wiring.json"
    path.write_text(json.dumps(trail))
    first = repo_index.load_repo_index(GRAPH, path).to_json()
    trail["nodes"].reverse()
    path.write_text(json.dumps(trail))
    assert repo_index.load_repo_index(GRAPH, path).to_json() == first


def test_repo_index_accepts_trail_file_ids_with_spaces(tmp_path):
    path = "source files/module.py"
    identifier = f"{path}#run"
    trail = tmp_path / "wiring.json"
    trail.write_text(
        json.dumps(
            {
                "meta": {"version": 1},
                "nodes": [
                    {"id": path, "path": path, "kind": "file", "span": "L1-L8"},
                    {"id": identifier, "path": path, "kind": "function", "span": "L2-L4"},
                ],
                "edges": [
                    {
                        "source": path,
                        "target": identifier,
                        "relation": "contains",
                        "confidence": "extracted",
                    }
                ],
            }
        )
    )
    index = repo_index.load_repo_index(GRAPH, trail)
    assert index.coverage.symbols_only == (path,)
    assert index.symbols.edges[0].target == identifier
