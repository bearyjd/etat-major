import json

import pytest

from etat_major.cli import main
from test_cli_json import FIXTURES, read_envelope

FIXTURE_DIR = FIXTURES / "gradle"


@pytest.fixture
def drift_args(tmp_path):
    root = tmp_path / "demo"
    for module in ("app", "libraries/core", "unused"):
        module_dir = root / module
        module_dir.mkdir(parents=True)
        (module_dir / "build.gradle.kts").touch()
    (root / "settings.gradle.kts").write_text(
        'include(":app", ":core", ":unused")\n'
        'project(":core").projectDir = file("libraries/core")\n',
        encoding="utf-8",
    )
    (root / "app/build.gradle.kts").write_text(
        "dependencies {\n"
        '    implementation(project(":core"))\n'
        '    testImplementation(project(":unused"))\n'
        "}\n",
        encoding="utf-8",
    )
    return [
        "gradle",
        "drift",
        "--root",
        str(root),
        "--graph",
        str(FIXTURE_DIR / "drift-graph.json"),
        "--trail",
        str(FIXTURE_DIR / "drift-wiring.json"),
        "--format",
        "json",
    ]


def test_drift_compares_declarations_and_recorded_evidence(drift_args, capsys, tmp_path):
    assert main(drift_args) == 1
    output, envelope = read_envelope(capsys, "gradle-drift", 1)
    assert str(tmp_path) not in output
    assert [(i["field"], i["severity"]) for i in envelope["issues"]] == [("drift", "warning")]
    data = envelope["data"]
    assert data["modules_only_declared"] == [":unused"]
    assert data["modules_only_observed"] == [":orphan", ":scope-only"]

    (used,) = data["declared_and_used"]
    assert (used["source"], used["target"], used["evidence_count"]) == (":app", ":core", 3)
    assert {
        (e["layer"], e["relation"], e["provenance"], e["count"], e["confidence"])
        for e in used["evidence"]
    } == {
        ("floorplan", "import", "inferred", 1, None),
        ("trail", "calls", "verified", 1, "extracted"),
        ("trail", "extends", "inferred", 1, "inferred"),
    }

    (unused,) = data["declared_but_unused"]
    assert (unused["source"], unused["target"], unused["evidence_count"]) == (":app", ":unused", 0)
    assert unused["declarations"][0]["test_only"] is True

    (undeclared,) = data["used_but_undeclared"]
    assert (undeclared["source"], undeclared["target"]) == (":app", ":orphan")
    assert undeclared["declarations"] == []
    assert undeclared["evidence_count"] == 1

    assert main(drift_args) == 1
    assert capsys.readouterr().out == output


def test_drift_returns_success_for_agreeing_graphs(drift_args, capsys, tmp_path):
    root = tmp_path / "demo"
    (root / "settings.gradle.kts").write_text(
        'include(":app", ":core", ":orphan", ":scope-only")\n'
        'project(":core").projectDir = file("libraries/core")\n',
        encoding="utf-8",
    )
    (root / "app/build.gradle.kts").write_text(
        "dependencies {\n"
        '    implementation(project(":core"))\n'
        '    implementation(project(":orphan"))\n'
        "}\n",
        encoding="utf-8",
    )
    for module in ("orphan", "scope-only"):
        (root / module).mkdir()
        (root / module / "build.gradle.kts").touch()
    assert main(drift_args) == 0
    _, envelope = read_envelope(capsys, "gradle-drift", 0)
    assert len(envelope["data"]["declared_and_used"]) == 2


@pytest.mark.parametrize("flag", ["--graph", "--trail"])
def test_drift_rejects_invalid_adapter_input(drift_args, capsys, tmp_path, flag):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schema": "invalid"}), encoding="utf-8")
    drift_args[drift_args.index(flag) + 1] = str(invalid)
    assert main(drift_args) == 2
    _, envelope = read_envelope(capsys, "gradle-drift", 2)
    assert envelope["data"] is None


@pytest.mark.parametrize(("flag", "mib"), [("--graph", 2), ("--trail", 10)])
def test_drift_accepts_large_recorded_artifacts(drift_args, capsys, tmp_path, flag, mib):
    index = drift_args.index(flag) + 1
    with open(drift_args[index], encoding="utf-8") as stream:
        graph = json.load(stream)
    graph["padding"] = "x" * (mib * 1024 * 1024)
    large = tmp_path / "large.json"
    large.write_text(json.dumps(graph), encoding="utf-8")
    drift_args[index] = str(large)

    assert main(drift_args) == 1  # The fixture has candidate drift.
    _, envelope = read_envelope(capsys, "gradle-drift", 1)
    (used,) = envelope["data"]["declared_and_used"]
    assert used["evidence_count"] == 3


@pytest.mark.parametrize("flag", ["--graph", "--trail"])
def test_drift_bounds_recorded_artifacts(drift_args, capsys, tmp_path, flag):
    large = tmp_path / "large.json"
    with large.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    drift_args[drift_args.index(flag) + 1] = str(large)
    assert main(drift_args) == 2
    _, envelope = read_envelope(capsys, "gradle-drift", 2)
    (issue,) = envelope["issues"]
    assert (issue["path"], issue["field"]) == ("large.json", "JSON")
    assert "64 MiB" in issue["message"]


def _write_graph(tmp_path, **changes):
    data = json.loads((FIXTURE_DIR / "drift-graph.json").read_text(encoding="utf-8"))
    graph = tmp_path / "graph.json"
    graph.write_text(json.dumps(data | changes), encoding="utf-8")
    return graph


def _graph_with_import(tmp_path, source, target, *extra_paths):
    data = json.loads((FIXTURE_DIR / "drift-graph.json").read_text(encoding="utf-8"))
    files = [
        dict(data["files"][0], p=path, name=path.rsplit("/", 1)[-1])
        for path in (source, target, *extra_paths)
    ]
    links = [dict(data["links"][0], a=f"f:{source}", b=f"f:{target}")]
    return _write_graph(tmp_path, files=files, links=links)


def test_drift_rejects_invalid_floorplan_link(drift_args, capsys, tmp_path):
    graph = _write_graph(tmp_path, links=[{}])
    drift_args[drift_args.index("--graph") + 1] = str(graph)
    assert main(drift_args) == 2
    _, envelope = read_envelope(capsys, "gradle-drift", 2)
    (issue,) = envelope["issues"]
    assert issue["path"] == "graph.json"
    assert issue["field"].startswith("links")


def test_drift_chooses_longest_directory_prefix_without_trail(drift_args, capsys, tmp_path):
    root = tmp_path / "demo"
    (root / "settings.gradle.kts").write_text(
        'include(":app", ":core", ":core:child")', encoding="utf-8"
    )
    (root / "app/build.gradle.kts").write_text(
        'dependencies { implementation(project(":core:child")) }', encoding="utf-8"
    )
    graph = _graph_with_import(tmp_path, "app/App.kt", "core/child/Child.kt", "core/Core.kt")
    args = [*drift_args[:6], "--format", "json"]
    args[args.index("--graph") + 1] = str(graph)
    assert main(args) == 0
    _, envelope = read_envelope(capsys, "gradle-drift", 0)
    (edge,) = envelope["data"]["declared_and_used"]
    assert (edge["target"], edge["evidence_count"]) == (":core:child", 1)


def test_conventional_inference_does_not_steal_known_module_files(drift_args, capsys, tmp_path):
    graph = _graph_with_import(tmp_path, "app/vendor/src/App.kt", "libraries/core/Core.kt")
    args = [*drift_args[:5], str(graph), "--format", "json"]
    assert main(args) == 1
    _, envelope = read_envelope(capsys, "gradle-drift", 1)
    assert envelope["data"]["modules_only_observed"] == []
    assert envelope["data"]["declared_and_used"][0]["source"] == ":app"
