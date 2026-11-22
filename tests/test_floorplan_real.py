import json
from time import perf_counter

import pytest

from etat_major.cli import main
from etat_major.floorplan import FloorplanError, load_graph
from etat_major.refs import parse_ref
from test_cli_json import FIXTURES, read_envelope

GRAPH = FIXTURES / "floorplan/graph-real.json"
TRAIL = FIXTURES / "trail/wiring-kotlin.json"
APP = "app/src/main/kotlin/com/ventouxlabs/netlens/navigation/DeepLinkRouter.kt"


def _inputs():
    return ["--graph", str(GRAPH), "--trail", str(TRAIL), "--format", "json"]


def _write_graph(tmp_path, **changes):
    path = tmp_path / "graph.json"
    data = json.loads(GRAPH.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | changes), encoding="utf-8")
    return path


def test_real_graph_architecture():
    graph = load_graph(GRAPH, architecture=True)
    assert graph.project == "NetLens"
    assert len(graph.nodes) == 34
    assert len(graph.files) == 170
    assert len(graph.links) == 215
    assert {link.kind for link in graph.links} == {"import", "queue"}


def test_real_graph_plain():
    plain = load_graph(GRAPH)
    assert plain.resolve(parse_ref("fp:n:app.navigation"))
    assert plain.resolve(parse_ref(f"fp:f:{APP}"))


def test_legacy_project_string_is_still_accepted(tmp_path):
    path = _write_graph(
        tmp_path, project="netlens", links=[{"a": "n:app", "b": "n:core", "k": "import"}]
    )
    assert load_graph(path, architecture=True).project == "netlens"
    assert load_graph(path).has_node("app")


def test_invalid_project_name_reports_file_and_field(tmp_path):
    path = _write_graph(tmp_path, project={"name": 1})
    with pytest.raises(FloorplanError, match=r"graph\.json.*project\.name"):
        load_graph(path, architecture=True)


def test_real_index_with_trail(capsys):
    assert main(["index", *_inputs()]) == 0
    _, envelope = read_envelope(capsys, "index", 0)
    data = envelope["data"]
    assert data["repository"] == "NetLens"
    assert any(link["kind"] == "queue" for link in data["architecture"]["links"])
    assert any(file["path"] == APP for file in data["architecture"]["files"])
    assert any(node["path"] == APP for node in data["symbols"]["nodes"])


def test_real_trace_with_trail(workspace_dir, capsys):
    path = workspace_dir / "features/netlens/0031-latency-graph.md"
    trail_ref = f"trail:{APP}#resolveRoute"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("fp:n:ui.hostdetail", "fp:n:app.navigation")
        .replace("fp:f:app/src/net/Latency.kt", f"fp:f:{APP}")
        .removesuffix("---\n")
        + f"  - ref: {trail_ref}\n    relation: uses\n---\n",
        encoding="utf-8",
    )
    assert (
        main(["trace", "feature:netlens/0031", "--workspace", str(workspace_dir), *_inputs()]) == 0
    )
    _, envelope = read_envelope(capsys, "trace", 0)
    assert {item["ref"]: item["state"] for item in envelope["data"]["architecture"]} == {
        "fp:n:app.navigation": "existing",
        f"fp:f:{APP}": "built",
        trail_ref: "existing",
    }


def _matching_gradle_tree(root):
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))
    trail = json.loads(TRAIL.read_text(encoding="utf-8"))
    paths = {file["p"] for file in graph["files"]} | {node["path"] for node in trail["nodes"]}
    dirs = {path.split("/src/")[0] for path in paths if "/src/" in path}
    dirs.update(scope["prefix"] for scope in trail["meta"]["scopes"] if scope["prefix"])
    modules = sorted(":" + directory.replace("/", ":") for directory in dirs)
    (root / "settings.gradle.kts").write_text(
        "include(" + ", ".join(map(json.dumps, modules)) + ")\n", encoding="utf-8"
    )
    dependencies = {
        "app": (
            "core:network",
            "feature:celltower",
            "feature:devices",
            "feature:dnsleak",
            "feature:history",
            "feature:mdns",
            "feature:netlog",
            "feature:ping",
        ),
        "core/scan": ("core:network",),
        "core/scan-testing": ("core:data-testing", "core:scan"),
        "feature/celltower": ("core:network",),
        "feature/devices": ("core:network", "core:scan"),
        "feature/httptester": ("core:network-testing",),
        "feature/ipinfo": ("core:data-testing",),
        "feature/mdns": ("core:network",),
        "feature/monitor": ("core:network-testing",),
        "feature/netlog": ("core:data-testing", "core:network"),
        "feature/ping": ("core:network",),
    }
    for directory in sorted(dirs | {""}):
        module = root / directory
        module.mkdir(parents=True, exist_ok=True)
        declarations = "".join(
            f'    implementation(project(":{target}"))\n'
            for target in dependencies.get(directory, ())
        )
        (module / "build.gradle.kts").write_text(
            f"dependencies {{\n{declarations}}}\n", encoding="utf-8"
        )


def test_real_gradle_drift_with_trail(tmp_path, capsys):
    _matching_gradle_tree(tmp_path)
    assert main(["gradle", "drift", "--root", str(tmp_path), *_inputs()]) == 0
    _, envelope = read_envelope(capsys, "gradle-drift", 0)
    rows = envelope["data"]["declared_and_used"]
    assert len(rows) == 21
    assert {item["layer"] for row in rows for item in row["evidence"]} == {"floorplan", "trail"}


def test_open_kinds_are_retained_reported_and_sanitized(tmp_path, capsys):
    private = str(tmp_path / "private")
    remote = f"ssh://{tmp_path.name}/private"
    path = _write_graph(
        tmp_path,
        project={"name": "Example project", "root": private, "remote": remote},
        meta={"root": private, "repos": [{"path": private, "remote": remote}]},
        nodes=[
            {"id": "app", "kind": "feature", "paths": []},
            {"id": "child", "parent": "app", "kind": "future\x1b kind", "summary": private},
            {"id": "remote", "kind": remote},
        ],
        links=[
            {"a": f"f:{APP}", "b": "n:app", "k": "call", "desc": remote},
            {"a": "n:app", "b": "n:child", "k": "future link"},
            {"a": "n:child", "b": "n:app", "k": "external"},
            {"a": "n:child", "b": "n:app", "k": ""},
            {"a": "n:app", "b": "n:remote", "k": private},
        ],
        future={"nested": remote},
    )
    graph = load_graph(path, architecture=True)
    assert graph.nodes[1].kind == "future\x1b kind"
    assert [link.kind for link in graph.links] == ["call", "future link", "external", "", private]
    args = ["index", "--graph", str(path), "--trail", str(TRAIL)]
    assert main([*args, "--format", "json"]) == 0
    output, envelope = read_envelope(capsys, "index", 0)
    assert private not in output and remote not in output and "\\u001b" in output
    data = envelope["data"]
    assert data["repository"] == "Example project"
    assert data["coverage"]["unknown_node_kinds"] == ["[redacted location]", r"future\u001b kind"]
    assert data["coverage"]["unknown_link_kinds"] == [
        "",
        "[redacted location]",
        "external",
        "future link",
    ]
    assert {link["kind"] for link in data["architecture"]["links"]} == {
        "call",
        "future link",
        "external",
        "",
        "[redacted location]",
    }
    assert main(args) == 0
    output = capsys.readouterr().out
    assert private not in output and remote not in output
    assert r"future\u001b kind" in output and "future link" in output


def test_empty_node_kind_is_a_field_error(tmp_path):
    path = _write_graph(tmp_path, nodes=[{"id": "app", "kind": ""}])
    with pytest.raises(FloorplanError, match=r"graph\.json.*nodes\.0\.kind"):
        load_graph(path, architecture=True)


def test_large_real_shaped_graph_loads_quickly(tmp_path):
    data = json.loads(GRAPH.read_text(encoding="utf-8"))
    template = next(file for file in data["files"] if file["p"] == APP)
    files = [dict(template, p=f"app/src/generated/File{i}.kt") for i in range(9000)]
    path = _write_graph(tmp_path, files=data["files"] + files)
    assert 1_800_000 < path.stat().st_size < 2_400_000
    start = perf_counter()
    graph = load_graph(path, architecture=True)
    assert perf_counter() - start < 2.0
    assert len(graph.files) == 9170
    assert graph.files[-1].path == "app/src/generated/File8999.kt"
