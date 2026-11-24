"""Read a pair of Git commit snapshots and reconcile file renames."""

import os
import re
import selectors
import stat
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from types import MappingProxyType

from etat_major.localfiles import open_directory, read_text
from etat_major.text_safety import safe

_MAX_FILE = 64 * 1024 * 1024
_TIMEOUT = 15


class RenameError(ValueError):
    """The repository or revision pair could not be read."""

    def __init__(self, repo: Path, field: str, detail: str) -> None:
        super().__init__(f"{safe(repo.name, limit=100)}: {field}: {detail}")


def _metadata_entry(fd: int, name: str, *, directory: bool = False) -> None:
    try:
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("metadata symlink is not allowed")
    if not (stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode):
        raise ValueError("unexpected metadata file type")
    if not directory and info.st_size > _MAX_FILE:
        raise ValueError(f"{safe(name, limit=100)}: metadata file exceeds the 64 MiB limit")


def _reject_indirect(fd: int, *names: str) -> None:
    for name in names:
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise ValueError("indirect metadata is not supported")


def _inspect_metadata(fd: int) -> None:
    with os.scandir(fd) as entries:
        if any(entry.is_symlink() for entry in entries):
            raise ValueError("metadata symlink is not allowed")
    _reject_indirect(fd, "commondir", "gitdir", "config.worktree")
    for name in ("config", "HEAD", "packed-refs", "shallow"):
        _metadata_entry(fd, name)
    for name in ("objects", "refs", "info"):
        _metadata_entry(fd, name, directory=True)
    for name in ("refs/heads", "refs/tags", "refs/remotes", "objects/info", "objects/pack"):
        _metadata_entry(fd, name, directory=True)
    for name in ("refs/remotes/origin", "objects/info/commit-graphs", "reftable"):
        _metadata_entry(fd, name, directory=True)
    for bucket in range(256):
        _metadata_entry(fd, f"objects/{bucket:02x}", directory=True)
    for name in (
        "info/grafts",
        "info/attributes",
        "objects/info/commit-graph",
        "refs/remotes/origin/HEAD",
    ):
        _metadata_entry(fd, name)
    _reject_indirect(fd, "objects/info/alternates", "objects/info/http-alternates")


def _worktree_pointer(repo: Path, fd: int) -> Path:
    prefix = "gitdir: "
    raw = read_text(Path(".git"), 1, dir_fd=fd).removesuffix("\n")
    if not raw.startswith(prefix) or not raw[len(prefix) :] or "\n" in raw or "\0" in raw:
        raise ValueError("invalid gitdir pointer")
    target = repo.absolute() / raw[len(prefix) :]
    if target.parent.name != "worktrees" or target.name in {"", ".", ".."}:
        raise ValueError("expected a linked worktree gitdir")
    return target


@contextmanager
def _open_repository(repo: Path) -> Iterator[int]:
    with open_directory(repo) as root_fd:
        entry = Path(".git")
        mode = os.stat(entry, dir_fd=root_fd, follow_symlinks=False).st_mode
        if stat.S_ISDIR(mode):
            with open_directory(entry, root_fd) as fd:
                _inspect_metadata(fd)
                _guard_config(fd)
                yield fd
            return
        target = _worktree_pointer(repo, root_fd)
        with open_directory(target) as fd, open_directory(target.parent.parent) as common:
            _inspect_metadata(common)
            _reject_indirect(fd, "config", "config.worktree")
            _metadata_entry(fd, "HEAD")
            shared = read_text(Path("commondir"), 1, dir_fd=fd).removesuffix("\n")
            backlink = read_text(Path("gitdir"), 1, dir_fd=fd).removesuffix("\n")
            original = target / backlink
            if shared != "../.." or original.name != entry.name:
                raise ValueError("invalid linked worktree metadata")
            with open_directory(original.parent) as backlink_fd:
                if not os.path.samestat(os.fstat(root_fd), os.fstat(backlink_fd)):
                    raise ValueError("invalid linked worktree backlink")
            _guard_config(common)
            yield fd


def _read_stdout(
    process: subprocess.Popen, limit: int, exit_codes: tuple[int, ...]
) -> tuple[bytes, int]:
    if process.stdout is None:
        raise ValueError("Git output unavailable")
    deadline = monotonic() + _TIMEOUT
    result = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while selector.select(max(0, deadline - monotonic())):
            chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > limit:
                raise ValueError("Git output exceeds its size limit")
            if monotonic() >= deadline:
                raise ValueError("Git timed out")
        else:
            raise ValueError("Git timed out")
    status = process.wait(timeout=max(0, deadline - monotonic()))
    if status not in exit_codes:
        raise ValueError("Git could not read the requested data")
    return bytes(result), status


def _git_result(
    fd: int,
    args: tuple[str, ...],
    limit: int,
    *,
    use_repo: bool = True,
    exit_codes: tuple[int, ...] = (0,),
) -> tuple[bytes, int]:
    env = {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ATTR_NOSYSTEM": "1",
    }
    if use_repo:
        env["GIT_DIR"] = f"/proc/self/fd/{fd}"
    command = ("git", "--no-pager", "--bare", "-c", "core.attributesFile=/dev/null", *args)
    with subprocess.Popen(  # noqa: S603 - fixed Git commands, no shell or inherited Git settings
        command,
        cwd="/",
        env=env,
        pass_fds=(fd,),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            return _read_stdout(process, limit, exit_codes)
        finally:
            if process.poll() is None:
                process.kill()


def _git(fd: int, args: tuple[str, ...], limit: int, *, use_repo: bool = True) -> bytes:
    return _git_result(fd, args, limit, use_repo=use_repo)[0]


def _guard_config(fd: int) -> None:
    config = f"/proc/self/fd/{fd}/config"
    keys = _git(
        fd,
        ("config", "--file", config, "--no-includes", "-z", "--name-only", "--list"),
        1024 * 1024,
        use_repo=False,
    )
    if any(key.startswith((b"include.", b"includeif.")) for key in keys.lower().split(b"\0")):
        raise ValueError("Git config includes are not supported")


def _commit(repo: Path, fd: int, revision: str, field: str) -> str:
    if not revision or revision.startswith("-") or len(revision) > 1024:
        raise RenameError(repo, field, "expected a Git commit revision")
    try:
        raw = _git(fd, ("rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"), 128)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise RenameError(repo, field, "could not resolve a Git commit") from None
    if not re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\n", raw):
        raise RenameError(repo, field, "expected a Git commit id")
    return raw.rstrip().decode("ascii")


def _parse_renames(output: bytes) -> Mapping[str, str]:
    renamed: dict[str, str] = {}
    if output:
        *fields, end = output.split(b"\0")
        if end or len(fields) % 3:
            raise ValueError("invalid Git name-status data")
        for status, old, new in zip(fields[::3], fields[1::3], fields[2::3], strict=True):
            if not re.fullmatch(rb"R[0-9]{1,3}", status):
                raise ValueError("expected a Git rename status")
            for path in (old, new):
                if {b"", b".", b".."}.intersection(path.split(b"/")):
                    raise ValueError("expected repository-relative Git paths")
            renamed[os.fsdecode(old)] = os.fsdecode(new)
    return MappingProxyType(renamed)


def load_renames(repo: Path, old_revision: str, new_revision: str) -> Mapping[str, str]:
    """Return old-to-new path pairs from Git's default rename similarity threshold."""
    try:
        with _open_repository(repo) as fd:
            old = _commit(repo, fd, old_revision, "old_revision")
            new = _commit(repo, fd, new_revision, "new_revision")
            try:
                output = _git(
                    fd,
                    (
                        "diff",
                        "-M",
                        "--name-status",
                        "-z",
                        "--diff-filter=R",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--ignore-submodules=all",
                        old,
                        new,
                        "--",
                    ),
                    _MAX_FILE,
                )
                return _parse_renames(output)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise RenameError(repo, "diff", "could not read Git rename data") from None
    except RenameError:
        raise
    except ValueError as exc:
        detail = str(exc) if not isinstance(exc, UnicodeError) else "invalid metadata encoding"
        raise RenameError(repo, ".git", detail) from None
    except (OSError, RecursionError, subprocess.TimeoutExpired):
        raise RenameError(repo, ".git", "cannot read repository metadata") from None
