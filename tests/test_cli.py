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


def test_trace_unknown_feature_exit_1(capsys, workspace_dir):
    code, _, err = run(capsys, "trace", "feature:netlens/0999", "--workspace", str(workspace_dir))
    assert code == 1 and "not found" in err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["trace"],
        ["trace", "feature:netlens/0031"],  # workspace required
        ["bogus"],
        ["trace", "feature:0031", "--workspace", "."],  # bad ref spelling
        ["trace", "research:0007", "--workspace", "."],  # not a feature
        ["trace", "feature:netlens/0031", "--workspace", "/nonexistent-dir-xyz"],
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
