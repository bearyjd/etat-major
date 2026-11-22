import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from etat_major.cli import main


def snapshot(*roots: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for p in files:
            if p.is_file():
                out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run(capsys, *argv: str):
    code = main(list(argv))
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_trace_demo_prints_chain_and_exits_1_on_gap(capsys, workspace_dir, graph_file):
    code, out, _ = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file),
    )  # fmt: skip
    assert code == 1  # the demo contains a gap by design
    assert "decision:0013  rejected  related" in out
    assert "fp:f:app/src/net/Latency.kt  new  gap" in out
    assert "f2  unsourced" in out


def test_trace_without_graph_is_unverified_and_exit_0(capsys, workspace_dir):
    code, out, err = run(capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir))
    assert code == 0 and err == ""
    assert "unverified" in out and "gap" not in out


@pytest.mark.parametrize(
    ("symbol", "relation", "use_floorplan", "state", "code"),
    [
        ("_with_line", "modifies", True, "existing", 0),
        ("_with_line", "new", False, "built", 0),
        ("missing", "uses", False, "stale", 1),
        ("missing", "new", False, "gap", 1),
    ],
)
def test_trace_resolves_trail_links(
    capsys, workspace_dir, graph_file, symbol, relation, use_floorplan, state, code
):
    path = workspace_dir / "features/netlens/0031-latency-graph.md"
    ref = f"trail:src/etat_major/taskfile.py#{symbol}"
    body = path.read_text().replace(
        "fp:f:app/src/net/Latency.kt\n    relation: new", f"{ref}\n    relation: {relation}"
    )
    path.write_text(body)
    trail = Path(__file__).parent / "fixtures/trail/wiring.json"
    args = ("trace", "feature:netlens/0031", "--workspace", str(workspace_dir))
    floorplan = ("--graph", str(graph_file)) if use_floorplan else ()
    actual, out, err = run(capsys, *args, *floorplan, "--trail", str(trail))
    assert actual == code and not err
    assert f"{ref}  {relation}  {state}  human" in out
    floorplan_state = "existing" if use_floorplan else "unverified"
    assert f"fp:n:ui.hostdetail  modifies  {floorplan_state}  human" in out
    assert f"{ref}  {relation}  unverified  human" in run(capsys, *args, *floorplan)[1]


def test_trace_bad_trail_is_usage_error_with_safe_diagnostic(capsys, workspace_dir, tmp_path):
    trail = tmp_path / "wiring\x1b.json"
    trail.write_text(json.dumps({"meta": {"version": 2}}))
    code, out, err = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--trail", str(trail),
    )  # fmt: skip
    assert code == 2 and not out
    assert r"wiring\u001b.json" in err and "meta.version" in err
    assert "\x1b" not in err and str(tmp_path) not in err and "Traceback" not in err


def test_trace_output_is_deterministic(capsys, workspace_dir, graph_file):
    args = ("trace", "feature:netlens/0031", "--workspace", str(workspace_dir))
    assert run(capsys, *args)[1] == run(capsys, *args)[1]


def test_trace_exit_0_when_everything_built(capsys, workspace_dir, graph_file):
    data = json.loads(graph_file.read_text())
    data["files"].append({"p": "app/src/net/Latency.kt", "n": "net.scan"})
    graph_file.write_text(json.dumps(data))
    code, _, _ = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file),
    )  # fmt: skip
    assert code == 0


def test_trace_exit_1_on_validation_errors(capsys, workspace_dir):
    (workspace_dir / "research/0099-bad.md").write_text("not frontmatter")
    code, out, err = run(capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir))
    assert code == 1 and "0099-bad.md" in err and "RESEARCH" in out


def test_trace_unknown_feature_exit_2(capsys, workspace_dir):
    code, _, err = run(capsys, "trace", "feature:netlens/0999", "--workspace", str(workspace_dir))
    assert code == 2 and "not found" in err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["trace"],
        ["trace", "feature:netlens/0031"],  # workspace required
        ["bogus"],
        ["trace", "feature:0031", "--workspace", "."],  # bad ref spelling
        ["trace", "research:0007", "--workspace", "."],  # not a feature
        ["trace", "feature:netlens/0031", "--workspace", "nonexistent-dir-xyz"],
        ["decisions"],
        ["decisions", "list"],
    ],
)
def test_usage_errors_exit_2(capsys, argv):
    try:
        code = main(argv)
    except SystemExit as exc:  # argparse
        code = exc.code
    capsys.readouterr()
    assert code == 2


def test_bad_graph_exit_2(capsys, workspace_dir, graph_file):
    graph_file.write_text(json.dumps({"schema": "floorplan/graph@9"}))
    code, _, err = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file),
    )  # fmt: skip
    assert code == 2 and "floorplan/graph@9" in err


def test_decisions_list_includes_rejected_and_postponed(capsys, workspace_dir):
    path = workspace_dir / "decisions/0014-later.md"
    path.write_text(
        "---\nid: 0014\nquestion: Add a widget?\nstatus: postponed\ndecided_by: human\n---\n"
    )
    code, out, _ = run(capsys, "decisions", "list", "--workspace", str(workspace_dir))
    assert code == 0
    assert out.splitlines() == [
        "decision:0012  approved  human  Should NetLens add a live latency graph?",
        "decision:0013  rejected  human  Should NetLens sync scan history to a cloud service?",
        "decision:0014  postponed  human  Add a widget?",
    ]


def test_decisions_list_exit_1_on_validation_errors(capsys, workspace_dir):
    (workspace_dir / "decisions/0099-bad.md").write_text("nope")
    code, out, err = run(capsys, "decisions", "list", "--workspace", str(workspace_dir))
    assert code == 1 and "0099-bad.md" in err and "decision:0012" in out


def test_workspace_reports_only_first_200_issues(capsys, tmp_path):
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    for index in range(201):
        (decisions / f"{index:04}-bad.md").touch()
    (decisions / "0201.md").write_text(
        "---\nid: '0201'\nquestion: Example?\nstatus: proposed\n"
        "evidence: [research:9998, research:9999]\n---\n"
    )
    code, _, err = run(capsys, "decisions", "list", "--workspace", str(tmp_path))
    assert code == 1
    lines = err.splitlines()
    assert len(lines) == 201
    assert all(line.startswith("invalid: decisions/") for line in lines[:200])
    assert lines[-1] == "... 3 more issues"


def test_workspace_caps_entire_invalid_line_after_escaping(capsys, tmp_path):
    project = tmp_path / "features" / ("a" * 240)
    project.mkdir(parents=True)
    path = project / ("bad" + "\x1b" * 240 + ".md")
    path.write_text("---\nid: '1'\nproject: example\nstatus: idea\n---\n")
    code, _, err = run(capsys, "decisions", "list", "--workspace", str(tmp_path))
    assert code == 1
    (line,) = err.splitlines()
    assert line.startswith("invalid: features/")
    assert "field 'title'" in line
    assert "\x1b" not in line
    assert len(line) <= 512


def test_cli_performs_no_writes(capsys, workspace_dir, graph_file, monkeypatch):
    before = snapshot(workspace_dir, graph_file)

    def boom(*a, **k):
        raise AssertionError("write attempted")

    monkeypatch.setattr(Path, "write_text", boom)
    monkeypatch.setattr(Path, "write_bytes", boom)
    monkeypatch.setattr(Path, "mkdir", boom)
    monkeypatch.setattr(Path, "unlink", boom)
    run(capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file))  # fmt: skip
    run(capsys, "decisions", "list", "--workspace", str(workspace_dir))
    monkeypatch.undo()
    assert snapshot(workspace_dir, graph_file) == before


def test_console_script_module_runs(workspace_dir):
    proc = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "etat_major.cli",
            "decisions",
            "list",
            "--workspace",
            str(workspace_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0 and "decision:0012" in proc.stdout


@pytest.mark.parametrize("args", [[], ["trace"], ["decisions", "list"]])
def test_help_documents_exit_codes(capsys, args):
    with pytest.raises(SystemExit) as exc:
        main([*args, "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "Exit codes" in help_text and all(f"{n} " in help_text for n in range(3))


def test_decisions_list_on_file_is_usage_error(capsys, graph_file):
    code, _, err = run(capsys, "decisions", "list", "--workspace", str(graph_file))
    assert code == 2 and "not a directory" in err


@pytest.mark.parametrize("action", ["missing schema", "missing file"])
def test_trace_graph_missing_schema_or_file_exit_2(capsys, workspace_dir, graph_file, action):
    if action == "missing schema":
        graph_file.write_text("{}")
    else:
        graph_file.unlink()
    code, _, err = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file),
    )  # fmt: skip
    assert code == 2 and graph_file.name in err
    assert ("schema" if action == "missing schema" else "cannot read") in err


def test_trace_stale_without_gap_exits_1(capsys, workspace_dir, graph_file):
    data = json.loads(graph_file.read_text())
    data["nodes"] = [{"id": "other"}]
    data["files"].append({"p": "app/src/net/Latency.kt", "n": "net.scan"})
    graph_file.write_text(json.dumps(data))
    code, out, err = run(
        capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir),
        "--graph", str(graph_file),
    )  # fmt: skip
    assert code == 1 and "stale" in out and "gap" not in out and not err


def test_warnings_do_not_change_exit_codes(capsys, workspace_dir):
    path = workspace_dir / "decisions/0012-add-latency-graph.md"
    path.write_text(
        path.read_text().replace("features: [feature:netlens/0031]\n", "").replace("#f1", "#f2")
    )
    code, out, err = run(capsys, "trace", "feature:netlens/0031", "--workspace", str(workspace_dir))
    assert code == 0 and "one-sided" in out and "unsourced" in out and "invalid:" not in err
    code, _, err = run(capsys, "decisions", "list", "--workspace", str(workspace_dir))
    assert code == 0 and "warning:" in err and "one-sided" in err
