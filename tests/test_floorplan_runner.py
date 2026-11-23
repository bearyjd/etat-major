import json
import sys
from io import BytesIO
from pathlib import Path

import pytest

from etat_major.cli import main
from etat_major.taskfile import TaskFileError


def test_floorplan_cli_rejects_unapproved_operation(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["floorplan", "describe", "--copy", ".", "--source", "."])
    assert exc.value.code == 2
    assert "'describe'" in capsys.readouterr().err


@pytest.fixture
def runner(tmp_path, monkeypatch):
    from etat_major import floorplan_runner as wrapper

    source = tmp_path / "tool"
    bundle = source / "skills" / "floorplan"
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "assets").mkdir()
    for name in ("scan", "build", "refresh"):
        (bundle / "scripts" / f"{name}.mjs").write_text(f"fixture: {name}\n")
    (bundle / "assets" / "viewer.html").write_text("fixture")
    monkeypatch.setattr(wrapper, "_BUNDLE_DIGEST", wrapper._bundle_digest(bundle))
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "before.kt").write_text("fun before() = 1")
    (copy / "after.kt").write_text("fun before() = 1")
    node = tmp_path / "node"
    node.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json
import os
import pathlib
import sys
import time

script, root, *flags = sys.argv[1:]
operation = pathlib.Path(script).stem
root = pathlib.Path(root)
marker = root / ".calls"
with marker.open("a") as stream:
    details = [operation, flags, "OPENAI_API_KEY" in os.environ,
               os.environ.get("FLOORPLAN_UNATTENDED"), str(pathlib.Path.cwd())]
    stream.write(json.dumps(details) + "\n")
if (root / "require-full-discovery").exists():
    git_dir = pathlib.Path(os.environ["GIT_DIR"])
    assert (root / ".git").is_file()
    assert (root / ".git").read_bytes() == b""
    assert git_dir.parent == root.parent and git_dir != root
    assert (git_dir / "HEAD").is_file() and (git_dir / "objects").is_dir()
    assert os.environ["GIT_COMMON_DIR"] == str(git_dir)
    assert os.environ["GIT_WORK_TREE"] == str(root)
    (root / ".discovery").write_text(str(git_dir))
if (root / "slow").exists():
    time.sleep(10)
if (root / "large").exists():
    sys.stderr.write("x" * 65536)
if (root / "fail").exists():
    sys.stderr.write("private.invalid:repo")
    raise SystemExit(1)
if (root / "noop").exists():
    print(json.dumps({"schema": f"floorplan/{operation}-result@1", "ok": True}))
    raise SystemExit(0)
output = root / "floorplan"
cache = output / ".cache"
cache.mkdir(parents=True, exist_ok=True)
scan = {"version": 1, "root": str(root), "repos": [{"path": ".", "remote": None}], "files": [
    {"path": "before.kt", "repo": ".", "category": "code", "lang": "Kotlin",
     "loc": 1, "bytes": 16}], "routes": []}
if operation == "scan":
    (cache / "scan.json").write_text(json.dumps(scan))
else:
    file = "after.kt" if operation == "refresh" else "before.kt"
    graph = {"schema": "floorplan/graph@1", "meta": {"generatedAt": "2026-11-21T12:00:00Z"},
             "nodes": [{"id": "stable"}], "files": [{"p": file, "n": "stable"}],
             "routes": [], "links": []}
    (output / "graph.json").write_text(json.dumps(graph))
    if operation == "refresh":
        scan["files"][0]["path"] = file
        (cache / "scan.json").write_text(json.dumps(scan))
        (cache / "changes.json").write_text(json.dumps({
            "since": "2026-11-21T12:00:00Z", "at": "2026-11-21T12:01:00Z",
            "files": {"new": [], "edited": [], "moved": [{"from": "before.kt", "to": "after.kt"}],
                      "deleted": []}, "routes": {"new": [], "removed": [], "moved": []}}))
print(json.dumps({"schema": f"floorplan/{operation}-result@1", "ok": True,
                  "report": "untrusted report private.invalid:repo"}))
"""
    )
    node.chmod(0o700)
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setattr(wrapper.shutil, "which", lambda _: str(node))
    return wrapper, source, copy


def test_floorplan_cli_runs_only_fixed_operations_and_reports_rename(runner, capsys):
    _, source, copy = runner
    args = ["--copy", str(copy), "--source", str(source)]
    assert main(["floorplan", "scan", *args]) == 0
    (copy / "floorplan" / "architecture.json").write_text('{"nodes":[{"id":"stable"}]}')
    assert main(["floorplan", "build", *args]) == 0
    assert main(["floorplan", "refresh", *args]) == 0
    stdout = capsys.readouterr().out
    assert "floorplan/.cache/scan.json" in stdout and "floorplan/graph.json" in stdout
    assert "before.kt -> after.kt" in stdout and "1 of 1 Floorplan node IDs retained" in stdout
    assert str(copy) not in stdout and "private.invalid" not in stdout
    calls = [json.loads(line) for line in (copy / ".calls").read_text().splitlines()]
    assert calls == [
        ["scan", ["--json", "--unattended"], False, "1", str(copy)],
        ["build", ["--json", "--unattended"], False, "1", str(copy)],
        ["refresh", ["--from-code", "--json", "--unattended"], False, "1", str(copy)],
    ]


@pytest.mark.parametrize(
    "kind", ["symlink", "hardlink", "git", "modified-tool", "backslash", "lookalike"]
)
def test_floorplan_stops_before_running_unsafe_inputs(runner, tmp_path, kind):
    wrapper, source, copy = runner
    external = tmp_path / "external"
    external.write_text("untouched")
    if kind == "symlink":
        (copy / "unsafe").symlink_to(external)
    elif kind == "hardlink":
        (copy / "unsafe").hardlink_to(external)
    elif kind == "git":
        (copy / ".git").write_text("gitdir: ../external")
    elif kind == "modified-tool":
        (source / "skills/floorplan/assets/viewer.html").write_text("modified")
    elif kind == "backslash":
        (copy / "..\\..\\unsafe").touch()
    else:
        (copy / "nested／file.kt").touch()
    with pytest.raises(TaskFileError):
        wrapper.run_floorplan("scan", copy, source)
    assert not (copy / ".calls").exists()
    assert external.read_text() == "untouched"


@pytest.mark.parametrize("field", ["file", "repo", "wrapFile", "remote", "worktree"])
def test_floorplan_build_rejects_cache_paths_that_can_escape(runner, field):
    wrapper, source, copy = runner
    wrapper.run_floorplan("scan", copy, source)
    artifact = copy / "floorplan/.cache/scan.json"
    data = json.loads(artifact.read_text())
    if field == "file":
        data["files"][0]["path"] = "../outside"
    elif field == "repo":
        data["files"][0]["repo"] = "../outside"
    elif field == "wrapFile":
        data["routes"] = [{"file": "before.kt", "wrapFile": "../outside"}]
    elif field == "remote":
        data["repos"][0]["remote"] = "host.invalid:repo"
    else:
        data["repos"][0]["worktreeOf"] = "/out"

    artifact.write_text(json.dumps(data))
    (copy / "floorplan" / "architecture.json").write_text('{"nodes":[]}')
    with pytest.raises(TaskFileError, match=r"scan\.json"):
        wrapper.run_floorplan("build", copy, source)
    assert len((copy / ".calls").read_text().splitlines()) == 1


@pytest.mark.parametrize("failure", ["slow", "large", "fail"])
def test_floorplan_bounds_subprocess_and_hides_raw_report(runner, monkeypatch, failure):
    wrapper, source, copy = runner
    (copy / failure).touch()
    monkeypatch.setattr(wrapper, "_OUTPUT_LIMIT", 4096)
    if failure == "slow":
        monkeypatch.setattr(wrapper, "_TIMEOUT", 0.1)
    with pytest.raises(TaskFileError) as exc:
        wrapper.run_floorplan("scan", copy, source)
    assert "private.invalid" not in str(exc.value)


@pytest.mark.parametrize("operation", ["scan", "build", "refresh"])
def test_floorplan_requires_the_selected_step_to_rewrite_its_artifacts(runner, operation):
    wrapper, source, copy = runner
    wrapper.run_floorplan("scan", copy, source)
    (copy / "floorplan" / "architecture.json").write_text('{"nodes":[{"id":"stable"}]}')
    wrapper.run_floorplan("build", copy, source)
    (copy / "floorplan/.cache/changes.json").write_text('{"files":{"moved":[]}}')
    (copy / "noop").touch()
    with pytest.raises(TaskFileError, match="did not refresh"):
        wrapper.run_floorplan(operation, copy, source)


def test_floorplan_timeout_has_bounded_cleanup_even_when_signals_fail(runner, monkeypatch):
    wrapper, source, copy = runner
    events = []

    class Process:
        pid = 42
        stdout = BytesIO()
        stderr = BytesIO()

        def __enter__(self):
            raise AssertionError("unbounded process context cleanup")

        def wait(self, *, timeout):
            assert 0 < timeout < 5
            events.append("bounded reap")
            raise wrapper.subprocess.TimeoutExpired("floorplan", timeout)

    def deny_signal(name):
        def fail(pid, sig):
            assert pid == 42
            events.append(name)
            raise PermissionError("private system detail")

        return fail

    def drain(*args):
        raise ValueError("Floorplan step timed out")

    process = Process()
    monkeypatch.setattr(wrapper.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(wrapper, "_read_output", drain)
    monkeypatch.setattr(wrapper.os, "waitid", lambda *args: None)
    monkeypatch.setattr(wrapper.os, "killpg", deny_signal("process group"))
    monkeypatch.setattr(wrapper.os, "kill", deny_signal("leader"))
    with pytest.raises(TaskFileError, match="timed out") as failure:
        wrapper.run_floorplan("scan", copy, source)
    assert events == ["process group", "leader", "bounded reap"]
    assert process.stdout.closed and process.stderr.closed
    assert "private system detail" not in str(failure.value)


@pytest.mark.parametrize("argument", ["copy", "source"])
def test_floorplan_rejects_double_root_before_access(runner, monkeypatch, argument):
    wrapper, source, copy = runner
    paths = {"copy": copy, "source": source}
    paths[argument] = Path(f"/{paths[argument]}")

    def stop(*args):
        pytest.fail("ambiguous path reached bundle verification")

    monkeypatch.setattr(wrapper, "_bundle_digest", stop)
    with pytest.raises(TaskFileError, match="expected separate copy and source directories"):
        wrapper.run_floorplan("scan", **paths)


@pytest.mark.parametrize("separator", ["", "\u00a0", "\u3000", "\u2028", "\r"])
def test_floorplan_refuses_nested_mounts(runner, monkeypatch, tmp_path, separator):
    wrapper, source, copy = runner
    parent = tmp_path / f"mount{separator}parent"
    parent.mkdir()
    copy = copy.rename(parent / "copy")
    mount = copy / "nested"
    mount.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"42 13 8:1 /sender {mount} rw - ext4 /dev/sda rw\n")
    monkeypatch.setattr(wrapper, "_mountinfo", lambda: mountinfo)
    with pytest.raises(TaskFileError, match="mounted"):
        wrapper.run_floorplan("scan", copy, source)
    assert not (copy / ".calls").exists()


def test_floorplan_provisions_and_removes_private_full_depth_discovery(runner):
    wrapper, source, copy = runner
    (copy / "require-full-discovery").touch()
    wrapper.run_floorplan("scan", copy, source)
    metadata = copy.parent / (copy / ".discovery").read_text().split("/")[-1]
    assert not metadata.exists()
    assert not (copy / ".git").exists()
    (copy / "fail").touch()
    with pytest.raises(TaskFileError, match="Floorplan step failed"):
        wrapper.run_floorplan("scan", copy, source)
    metadata = copy.parent / (copy / ".discovery").read_text().split("/")[-1]
    assert not metadata.exists()
    assert not (copy / ".git").exists()
