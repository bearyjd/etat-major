import os
import shutil
import sys
from pathlib import Path

import pytest

from etat_major import trail_runner
from etat_major.localfiles import open_directory
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


def test_uses_empty_git_metadata_for_worktree(tmp_path, checkout, monkeypatch):
    source, disposable = checkout
    metadata = source / ".git" / "worktrees" / "disposable"
    metadata.mkdir(parents=True)
    (disposable / ".git").write_text(f"gitdir: {metadata}\n", encoding="utf-8")
    (source / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    executable = fake_trail(tmp_path, "pass")

    def inspect_environment(path, root, env):
        git_dir = Path(env["GIT_DIR"])
        assert git_dir == Path(env["HOME"]) / "git"
        assert Path(env["GIT_COMMON_DIR"]) == git_dir
        assert Path(env["GIT_WORK_TREE"]) == disposable
        assert (git_dir / "HEAD").is_file()
        assert (git_dir / "objects").is_dir()
        assert (git_dir / "refs").is_dir()
        assert not (git_dir / "config").exists()

    monkeypatch.setattr(trail_runner, "_run", inspect_environment)
    with pytest.raises(TrailRunError, match="fresh"):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize("alias_ancestor", [False, True])
def test_rejects_checkout_identity_alias(tmp_path, checkout, monkeypatch, alias_ancestor):
    source, disposable = checkout
    if alias_ancestor:
        disposable = disposable / "nested"
        disposable.mkdir()
    identities = {source: (1, 10), disposable.parent if alias_ancestor else disposable: (1, 10)}

    def identity(path):
        return identities.get(path, (1, path.stat().st_ino))

    monkeypatch.setattr(trail_runner, "_directory_identity", identity, raising=False)
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="separate"):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize("entry_type", ["symlink", "hardlink", "fifo", "mount"])
def test_rejects_unsafe_nested_entry(tmp_path, checkout, entry_type):
    source, disposable = checkout
    target = source / "data"
    target.touch()
    nested = disposable / "nested"
    nested.mkdir()
    entry = nested / "entry"
    if entry_type == "symlink":
        entry.symlink_to(target)
    elif entry_type == "hardlink":
        os.link(target, entry)
    elif entry_type == "fifo":
        os.mkfifo(entry)
    else:
        entry.touch()

    if entry_type == "mount":
        with (
            open_directory(nested) as fd,
            pytest.raises(TrailRunError, match="mounted entry"),
        ):
            trail_runner._walk_tree(disposable, fd, Path("nested"), -1, [0])
    else:
        executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
        with pytest.raises(TrailRunError, match="entry in checkout|file in checkout"):
            run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize("limit", ["_TREE_DEPTH_LIMIT", "_TREE_ENTRY_LIMIT"])
def test_bounds_tree_inspection(tmp_path, checkout, monkeypatch, limit):
    source, disposable = checkout
    (disposable / "one" / "two").mkdir(parents=True)
    monkeypatch.setattr(trail_runner, limit, 1)
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="inspection limits"):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize("layout", ["graft", ".trail/cache"])
def test_rejects_cached_workspace_index(tmp_path, checkout, layout):
    source, disposable = checkout
    directory = disposable / layout
    directory.mkdir(parents=True)
    (directory / "workspace.json").write_text('{"version": 1, "children": []}', encoding="utf-8")
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="workspace.json"):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("out.symlink_to(fixture)", "independent regular file"),
        ("out.hardlink_to(fixture)", "independent regular file"),
        (
            'other = Path(".trail/cache/.graph/wiring.json")\n'
            "other.parent.mkdir(parents=True)\n"
            "shutil.copyfile(fixture, other)\n"
            "shutil.copyfile(fixture, out)",
            "exactly one fresh",
        ),
    ],
)
def test_rejects_unsafe_or_ambiguous_output(tmp_path, checkout, body, error):
    source, disposable = checkout
    fixture = tmp_path / "wiring.json"
    shutil.copyfile(_WIRING, fixture)
    executable = fake_trail(
        tmp_path,
        f"""
from pathlib import Path
import shutil
fixture = Path({str(fixture)!r})
out = Path("graft/.graph/wiring.json")
out.parent.mkdir(parents=True)
{body}
""",
    )
    with pytest.raises(TrailRunError, match=error):
        run_trail(disposable, source_root=source, executable=executable)


@pytest.mark.parametrize("tool_root", ["source", "disposable"])
@pytest.mark.parametrize("as_runtime", [False, True])
def test_rejects_tool_paths_inside_checkouts(tmp_path, checkout, tool_root, as_runtime):
    source, disposable = checkout
    inside = source if tool_root == "source" else disposable
    executable = fake_trail(tmp_path if as_runtime else inside, "pass")
    runtime = str(inside) if as_runtime else "/usr/bin"
    with pytest.raises(TrailRunError, match="tools outside checkout"):
        run_trail(disposable, source_root=source, executable=executable, runtime_path=runtime)


def test_rejects_checkout_parent_with_path_separator(tmp_path, checkout):
    source, disposable = checkout
    parent = tmp_path / f"checkout{os.pathsep}parent"
    parent.mkdir()
    disposable = disposable.rename(parent / disposable.name)
    executable = fake_trail(tmp_path, "raise AssertionError('must not run')")
    with pytest.raises(TrailRunError, match="search-path separator"):
        run_trail(disposable, source_root=source, executable=executable)


def test_excludes_runtime_files_from_both_checkouts(tmp_path, checkout, monkeypatch):
    source, disposable = checkout
    marker = tmp_path / "home-path"
    monkeypatch.setenv("TMPDIR", str(disposable))
    executable = fake_trail(
        tmp_path,
        f"""
import os
import shutil
from pathlib import Path

root = Path.cwd()
source = Path({str(source)!r})
home = Path(os.environ["HOME"])
git_dir = Path(os.environ["GIT_DIR"])
assert home.is_absolute()
assert not home.is_relative_to(root)
assert not home.is_relative_to(source)
assert git_dir.parent == home
for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "TMPDIR"):
    assert Path(os.environ[key]) == home
(home / "runtime.py").touch()
assert "runtime.py" not in [path.name for path in root.rglob("*")]
out = Path("graft/.graph/wiring.json")
out.parent.mkdir(parents=True)
shutil.copyfile({str(_WIRING)!r}, out)
Path({str(marker)!r}).write_text(str(home), encoding="utf-8")
""",
    )
    result = run_trail(disposable, source_root=source, executable=executable)
    assert all("runtime.py" not in symbol.path for symbol in result.index.symbols)
    assert not Path(marker.read_text(encoding="utf-8")).exists()
