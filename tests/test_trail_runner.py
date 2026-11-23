import shutil
import sys
from pathlib import Path

import pytest

from etat_major import trail_runner
from etat_major.trail import TrailError
from etat_major.trail_runner import TrailRunError, run_trail

_WIRING = Path(__file__).parent / "fixtures" / "trail" / "wiring-kotlin.json"


@pytest.fixture
def checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    disposable = tmp_path / "disposable"
    disposable.mkdir()
    return source, disposable


def fake_trail(tmp_path, body):
    executable = tmp_path / "trail"
    executable.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    executable.chmod(0o700)
    return executable


@pytest.mark.parametrize("layout", ["graft", ".trail/cache"])
def test_build_loads_graph_with_fixed_flags_and_no_host_environment(
    tmp_path, checkout, monkeypatch, layout
):
    source, disposable = checkout
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("NODE_OPTIONS", "--bogus")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "99")
    executable = fake_trail(
        tmp_path,
        f"""
import os
import sys
from pathlib import Path
import shutil
assert sys.argv[1:] == [
    "build", "--no-reuse", "--no-follow-submodules", "--no-follow-nested-repos",
    "--no-gitignore", "--no-ignore",
]
assert Path.cwd() == Path({str(disposable)!r})
assert os.environ["DO_NOT_TRACK"] == "1"
assert os.environ["GIT_CONFIG_VALUE_0"] == "false"
assert os.environ["GIT_ALLOW_PROTOCOL"] == ""
assert os.environ["HOME"] != {str(Path.home())!r}
assert "ANTHROPIC_API_KEY" not in os.environ
assert "NODE_OPTIONS" not in os.environ
assert os.environ["PATH"] == "/usr/bin"
out = Path({layout!r}) / ".graph" / "wiring.json"
out.parent.mkdir(parents=True)
shutil.copyfile({str(_WIRING)!r}, out)
""",
    )
    result = run_trail(
        disposable, source_root=source, executable=executable, runtime_path="/usr/bin"
    )
    assert result.artifact == Path(layout) / ".graph" / "wiring.json"
    assert result.index.symbols


def test_refuses_source_inside_disposable_and_internal_symlinks(tmp_path, checkout):
    source, disposable = checkout
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="separate"):
        run_trail(source, source_root=source, executable=executable)
    nested = source / "nested"
    nested.mkdir()
    with pytest.raises(TrailRunError, match="separate"):
        run_trail(nested, source_root=source, executable=executable)
    (disposable / ".trail").symlink_to(source, target_is_directory=True)
    with pytest.raises(TrailRunError, match="symlink"):
        run_trail(disposable, source_root=source, executable=executable)


def test_rejects_stale_or_invalid_artifact(tmp_path, checkout):
    source, disposable = checkout
    existing = disposable / "graft/.graph/wiring.json"
    existing.parent.mkdir(parents=True)
    shutil.copyfile(_WIRING, existing)
    executable = fake_trail(tmp_path, "pass")
    with pytest.raises(TrailRunError, match="fresh"):
        run_trail(disposable, source_root=source, executable=executable)
    executable = fake_trail(
        tmp_path,
        "from pathlib import Path\n"
        'Path("graft/.graph/wiring.json").write_text(\'{"meta":{"version":2}}\')',
    )
    with pytest.raises(TrailError, match="meta.version"):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("raise SystemExit(8)", "exited with status 8"),
        ("import time; time.sleep(10)", "timed out"),
        ('import os; os.write(2, b"PRIVATE" * 20000)', "output limit"),
    ],
)
def test_reports_bounded_process_failure(tmp_path, checkout, monkeypatch, body, expected):
    source, disposable = checkout
    executable = fake_trail(tmp_path, body)
    monkeypatch.setattr(trail_runner, "_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(trail_runner, "_OUTPUT_LIMIT_BYTES", 128)
    with pytest.raises(TrailRunError, match=expected) as error:
        run_trail(disposable, source_root=source, executable=executable)
    assert "PRIVATE" not in str(error.value)
    assert str(disposable) not in str(error.value)


def test_rejects_a_workspace_before_starting_tool(tmp_path, checkout):
    source, disposable = checkout
    for child_name in ("project-one", "project-two"):
        (disposable / child_name / ".git").mkdir(parents=True)
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="single-repository"):
        run_trail(disposable, source_root=source, executable=executable)


def test_uses_canonical_executable_and_runtime_directory(tmp_path, checkout, monkeypatch):
    source, disposable = checkout
    executable = fake_trail(tmp_path, "pass")
    alias = tmp_path / "tool-alias"
    alias.symlink_to(executable)
    runtime = tmp_path / "runtime"
    runtime.symlink_to("/usr/bin", target_is_directory=True)
    calls = []

    def capture(path, root, env):
        calls.append((path, root, env["PATH"]))

    monkeypatch.setattr(trail_runner, "_run", capture)
    with pytest.raises(TrailRunError, match="fresh"):
        run_trail(disposable, source_root=source, executable=alias, runtime_path=str(runtime))
    assert calls == [(executable, disposable, "/usr/bin")]


def test_rejects_runtime_alias_resolving_to_path_list(tmp_path, checkout):
    source, disposable = checkout
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    directory = tmp_path / "trusted:untrusted"
    directory.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(directory, target_is_directory=True)
    with pytest.raises(TrailRunError, match="runtime directories"):
        run_trail(disposable, source_root=source, executable=executable, runtime_path=str(runtime))
