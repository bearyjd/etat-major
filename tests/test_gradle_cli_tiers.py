import json
import os
import shutil
import subprocess

from etat_major.cli import main
from test_cli_json import FIXTURES, read_envelope
from test_gradle import deps


def test_real_portscan_deps_and_drift(tmp_path, capsys):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURES / "gradle-real", root)
    subprocess.run(  # noqa: S603
        ["git", "init", "-b", "main"],  # noqa: S607
        cwd=root,
        env={"PATH": os.defpath, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"},
        check=True,
        capture_output=True,
    )
    source = "feature/portscan/src/main/kotlin/PortScan.kt"
    targets = [f"core/{name}/src/main/kotlin/Library.kt" for name in ("billing", "ui")]
    explicit_targets = [
        f"core/{name}/src/main/kotlin/Library.kt" for name in ("scan", "network", "data")
    ]
    libraries = targets + explicit_targets
    for path in [source, *libraries]:
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    deps_data = deps(root, capsys)["data"]
    assert [(row["source"], row["target"]) for row in deps_data["implicit_edges"]] == [
        (":feature:portscan", ":core:billing"),
        (":feature:portscan", ":core:ui"),
    ]
    graph = _graph(tmp_path, [source, *libraries], [(source, target) for target in libraries])
    args = ["gradle", "drift", "--root", str(root), "--graph", str(graph), "--format", "json"]
    assert main(args) == 0
    output, envelope = read_envelope(capsys, "gradle-drift", 0)
    data = envelope["data"]
    assert data["used_but_undeclared"] == []
    assert data["summary"]["declared_implicit"] == 2
    assert [row["target"] for row in data["declared_implicit"]] == [":core:billing", ":core:ui"]
    for row in data["declared_implicit"]:
        (edge,) = row["declarations"]
        assert (edge["plugin_id"], edge["plugin_class"], edge["implicit"]) == (
            "netlens.android.feature",
            "AndroidFeatureConventionPlugin",
            True,
        )
    assert main(args) == 0
    assert capsys.readouterr().out == output


def _graph(tmp_path, paths, links):
    data = json.loads((FIXTURES / "gradle/drift-graph.json").read_text(encoding="utf-8"))
    data["files"] = [dict(data["files"][0], p=path) for path in paths]
    data["links"] = [
        dict(data["links"][0], a=f"f:{source}", b=f"f:{target}") for source, target in links
    ]
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _trail(tmp_path, source, target):
    nodes = [
        dict(id=f"{source}#Call{i}", path=source, kind="function", span="L1-L2") for i in range(44)
    ]
    nodes.append(dict(id=f"{target}#Target", path=target, kind="function", span="L1-L2"))
    edges = [
        dict(source=node["id"], target=nodes[-1]["id"], relation="calls", confidence="inferred")
        for node in nodes[:-1]
    ]
    path = tmp_path / "wiring.json"
    path.write_text(
        json.dumps(dict(meta={"version": 1}, nodes=nodes, edges=edges)), encoding="utf-8"
    )
    return path


def test_weak_drift_is_only_detailed_with_verbose(tmp_path, capsys):
    (tmp_path / "settings.gradle.kts").write_text('include(":app", ":other")', encoding="utf-8")
    source, target = "app/src/main/App.kt", "other/src/main/Other.kt"
    graph = _graph(tmp_path, [source, target], [])
    trail = _trail(tmp_path, source, target)
    args = [
        "gradle",
        "drift",
        "--root",
        str(tmp_path),
        "--graph",
        str(graph),
        "--trail",
        str(trail),
    ]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert output.splitlines()[0].startswith("Tier")
    assert "call_only" in output
    assert ":app -> :other" not in output
    assert "candidate dependency or module differences" not in output
    assert main([*args, "--verbose"]) == 0
    assert ":app -> :other  evidence=44" in capsys.readouterr().out
    assert main([*args, "--format", "json"]) == 0
    _, envelope = read_envelope(capsys, "gradle-drift", 0)
    data = envelope["data"]
    assert data["summary"]["call_only"] == 1
    assert data["used_but_undeclared"] == []
    (weak,) = data["call_only"]
    assert weak["tier"] == "call_only" and weak["rank"] > 1 and weak["reasons"]
    assert weak["evidence_count"] == 44


def test_invalid_graph_escapes_control_characters_in_file_name(tmp_path, capsys):
    (tmp_path / "settings.gradle.kts").write_text('include(":app")', encoding="utf-8")
    graph = tmp_path / "bad\x1b.json"
    graph.write_text("{", encoding="utf-8")
    args = ["gradle", "drift", "--root", str(tmp_path), "--graph", str(graph), "--format", "json"]
    assert main(args) == 2
    output, envelope = read_envelope(capsys, "gradle-drift", 2)
    assert str(tmp_path) not in output
    assert envelope["issues"][0]["path"] == r"bad\u001b.json"
