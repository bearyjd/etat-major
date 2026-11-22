"""Read a pair of Git commit snapshots and reconcile file renames."""

import os
import re
import selectors
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from time import monotonic
from types import MappingProxyType

from etat_major.localfiles import open_directory
from etat_major.text_safety import safe

_MAX_FILE = 64 * 1024 * 1024
_MAX_ENTRIES = 100_000
_TIMEOUT = 15
_UNSUPPORTED = {"commondir", "gitdir", "config.worktree", "alternates", "http-alternates"}


class RenameError(ValueError):
    """The repository or revision pair could not be read."""

    def __init__(self, repo: Path, field: str, detail: str) -> None:
        super().__init__(f"{safe(repo.name, limit=100)}: {field}: {detail}")


def _inspect_metadata(fd: int) -> None:
    # Git opens the files itself. Reject indirect metadata and unsafe entries first.
    entries = 0
    for _, dirs, files, directory in os.fwalk(".", dir_fd=fd, onerror=_raise_walk_error):
        entries += len(dirs) + len(files)
        if entries > _MAX_ENTRIES:
            raise ValueError("too many metadata entries")
        for name in (*dirs, *files):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("metadata symlink is not allowed")
            if name in _UNSUPPORTED:
                raise ValueError("indirect metadata is not supported")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("expected regular metadata files and directories")
            if info.st_size > _MAX_FILE and stat.S_ISREG(info.st_mode):
                raise ValueError("metadata file exceeds the 64 MiB limit")


def _raise_walk_error(exc: OSError) -> None:
    raise exc


def _read_stdout(process: subprocess.Popen, limit: int) -> bytes:
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
    if process.wait(timeout=max(0, deadline - monotonic())):
        raise ValueError("Git could not read the requested data")
    return bytes(result)


def _git(fd: int, args: tuple[str, ...], limit: int, *, use_repo: bool = True) -> bytes:
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
            return _read_stdout(process, limit)
        finally:
            if process.poll() is None:
                process.kill()


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
        with open_directory(repo / ".git") as fd:
            try:
                _inspect_metadata(fd)
                _guard_config(fd)
            except ValueError as exc:
                raise RenameError(repo, ".git", str(exc)) from None
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
    except (OSError, RecursionError, subprocess.TimeoutExpired):
        raise RenameError(repo, ".git", "cannot read repository metadata") from None
