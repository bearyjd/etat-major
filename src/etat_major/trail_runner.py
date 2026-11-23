"""Build a version-checked Trail graph in a caller-owned disposable checkout."""

import os
import selectors
import signal
import stat
import subprocess  # noqa: S404 - the single Trail runner permitted by docs/NEXT.md
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

from etat_major.localfiles import open_directory, open_relative_directory
from etat_major.taskfile import TaskFileError
from etat_major.trail import SymbolIndex, load_wiring

_BUILD_ARGS = (
    "build",
    "--no-reuse",
    "--no-follow-submodules",
    "--no-follow-nested-repos",
    "--no-gitignore",
    "--no-ignore",
)
_LAYOUTS = (Path("graft"), Path(".trail/cache"))
_WIRING = Path(".graph/wiring.json")
_TIMEOUT_SECONDS = 120
_OUTPUT_LIMIT_BYTES = 2 * 1024 * 1024
_TREE_ENTRY_LIMIT = 100_000
_TREE_DEPTH_LIMIT = 64


class TrailRunError(TaskFileError):
    """The disposable checkout or Trail invocation failed a runner check."""


@dataclass(frozen=True)
class TrailRun:
    artifact: Path
    index: SymbolIndex


def run_trail(
    disposable_root: Path,
    *,
    source_root: Path,
    executable: Path,
    runtime_path: str = os.defpath,
) -> TrailRun:
    """Run trusted Trail 0.30.5, then load the fresh graph it produced.

    The caller owns the disposable checkout exclusively during the build and
    supplies a trusted Trail executable and trusted runtime directories.
    """
    root = _checkout(disposable_root)
    source = _checkout(source_root)
    if _overlapping_checkouts(root, source):
        raise TrailRunError(root, "disposable_root", "expected a checkout separate from the source")
    if os.pathsep in str(root.parent):
        raise TrailRunError(
            root, "disposable_root", "parent path contains the search-path separator"
        )
    tool, path_env = _trusted_tools(root, source, executable, runtime_path)
    _check_tree(root)
    before = _artifacts(root)
    try:
        with TemporaryDirectory(prefix=".etat-major-trail-", dir=root) as home:
            _prepare_git_metadata(Path(home) / "git")
            _run(tool, root, _environment(home, path_env, root))
    except OSError:
        raise TrailRunError(root, "trail build", "could not start or finish Trail") from None
    fresh = [path for path, stamp in _artifacts(root).items() if before.get(path) != stamp]
    if len(fresh) != 1:
        raise TrailRunError(root, "wiring.json", "expected exactly one fresh Trail graph")
    return TrailRun(fresh[0], load_wiring(root / fresh[0]))


def _checkout(path: Path) -> Path:
    try:
        if ".." not in path.parts:
            root = path.absolute()
            with open_directory(root):
                return root
    except (OSError, ValueError):
        pass
    raise TrailRunError(path, "checkout", "expected a real directory without symlinks or '..'")


def _directory_identity(path: Path) -> tuple[int, int]:
    with open_directory(path) as fd:
        info = os.fstat(fd)
    return info.st_dev, info.st_ino


def _overlapping_checkouts(root: Path, source: Path) -> bool:
    try:
        root_id = _directory_identity(root)
        source_id = _directory_identity(source)
        return (
            root_id == source_id
            or any(_directory_identity(parent) == source_id for parent in root.parents)
            or any(_directory_identity(parent) == root_id for parent in source.parents)
        )
    except OSError:
        raise TrailRunError(
            root, "disposable_root", "could not verify checkout identities"
        ) from None


def _trusted_tools(
    root: Path, source: Path, executable: Path, runtime_path: str
) -> tuple[Path, str]:
    paths = (executable, *(Path(directory) for directory in runtime_path.split(os.pathsep)))
    tool, *directories = (_resolve_tool_path(root, source, path) for path in paths)
    if not tool.is_file() or not os.access(tool, os.X_OK):
        raise TrailRunError(root, "trail executable", "expected an executable file")
    if any(os.pathsep in str(directory) or not directory.is_dir() for directory in directories):
        raise TrailRunError(root, "PATH", "expected existing runtime directories")
    return tool, os.pathsep.join(map(str, directories))


def _resolve_tool_path(root: Path, source: Path, path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True) if path.is_absolute() else None
    except (OSError, RuntimeError, ValueError):
        resolved = None
    if resolved is None or resolved.is_relative_to(root) or resolved.is_relative_to(source):
        raise TrailRunError(root, "trail executable", "expected absolute tools outside checkout")
    return resolved


def _check_tree(root: Path) -> None:
    try:
        with open_directory(root) as fd:
            _walk_tree(root, fd, Path(), os.fstat(fd).st_dev, [0])
            if _workspace_parent(fd):
                raise TrailRunError(
                    root, "disposable_root", "expected a single-repository checkout"
                )
    except OSError:
        raise TrailRunError(root, "disposable_root", "could not inspect checkout") from None


def _has_git(fd: int) -> bool:
    try:
        os.stat(".git", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _workspace_parent(fd: int) -> bool:
    if _has_git(fd):
        return False
    children = 0
    with os.scandir(fd) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                with open_directory(Path(entry.name), fd) as child:
                    children += _has_git(child)
                if children == 2:
                    return True
    return False


def _walk_tree(root: Path, fd: int, relative: Path, device: int, count: list[int]) -> None:
    with os.scandir(fd) as entries:
        for entry in entries:
            path = relative / entry.name
            count[0] += 1
            if count[0] > _TREE_ENTRY_LIMIT or len(path.parts) > _TREE_DEPTH_LIMIT:
                raise TrailRunError(root, "disposable_root", "checkout exceeds inspection limits")
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or info.st_dev != device:
                raise TrailRunError(root, "disposable_root", "symlink or mounted entry in checkout")
            if path in (layout / "workspace.json" for layout in _LAYOUTS):
                raise TrailRunError(root, "workspace.json", "expected a single-repository checkout")
            if stat.S_ISDIR(info.st_mode):
                with open_directory(Path(entry.name), fd) as child:
                    _walk_tree(root, child, path, device, count)
            elif not stat.S_ISREG(info.st_mode) or (
                info.st_nlink != 1 and path.parts[:2] != (".git", "objects")
            ):
                raise TrailRunError(
                    root, "disposable_root", "special or hard-linked file in checkout"
                )


def _artifacts(root: Path) -> dict[Path, tuple[int, int, int, int]]:
    found = {}
    try:
        with open_directory(root) as fd:
            for path in (layout / _WIRING for layout in _LAYOUTS):
                try:
                    with open_relative_directory(path.parent, fd) as directory:
                        info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise TrailRunError(path, "wiring.json", "expected an independent regular file")
                found[path] = (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    except OSError:
        raise TrailRunError(root, "wiring.json", "could not inspect graph location") from None
    return found


def _prepare_git_metadata(git_dir: Path) -> None:
    # Give Trail a Git work tree for ignore processing without loading its local
    # Git config, index, or linked worktree metadata.
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/trail-scan\n", encoding="ascii")


def _environment(home: str, runtime_path: str, root: Path) -> dict[str, str]:
    return {
        "PATH": runtime_path,
        "LANG": "C.UTF-8",
        "HOME": home,
        "XDG_CONFIG_HOME": home,
        "XDG_CACHE_HOME": home,
        "XDG_DATA_HOME": home,
        "XDG_STATE_HOME": home,
        "TMPDIR": home,
        "DO_NOT_TRACK": "1",
        "CI": "1",
        "GIT_DIR": str(Path(home) / "git"),
        "GIT_COMMON_DIR": str(Path(home) / "git"),
        "GIT_WORK_TREE": str(root),
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(root.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
    }


def _run(executable: Path, root: Path, environment: dict[str, str]) -> None:
    deadline = monotonic() + _TIMEOUT_SECONDS
    with subprocess.Popen(  # noqa: S603 - trusted caller executable and fixed arguments
        (str(executable), *_BUILD_ARGS),
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    ) as process:
        try:
            _drain_output(process, deadline, root)
            _observe_exit(process.pid, root, deadline)
        finally:
            _kill_reserved_group(process.pid)
        status = process.wait()
    if status != 0:
        raise TrailRunError(root, "trail build", f"exited with status {status}")


def _observe_exit(pid: int, root: Path, deadline: float) -> None:
    while not os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TrailRunError(root, "trail build", "timed out")
        sleep(min(0.01, remaining))


def _kill_reserved_group(pid: int) -> None:
    # Confirm the leader is still our unreaped child, even if an error
    # interrupted the build. Reaping first could let another group reuse pid.
    try:
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        os.killpg(pid, signal.SIGKILL)
    except (ChildProcessError, ProcessLookupError):
        pass


def _drain_output(process: subprocess.Popen, deadline: float, root: Path) -> None:
    if process.stdout is None:
        raise TrailRunError(root, "trail build", "could not open output pipe")
    fd = process.stdout.fileno()
    available = _OUTPUT_LIMIT_BYTES
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_READ)
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TrailRunError(root, "trail build", "timed out")
            chunk = os.read(fd, min(65536, available + 1))
            if not chunk:
                return
            available -= len(chunk)
            if available < 0:
                raise TrailRunError(root, "trail build", "exceeded the output limit")
