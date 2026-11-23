"""Open symlink-free directories and read bounded regular files."""

import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from heapq import nsmallest
from itertools import islice
from pathlib import Path
from secrets import token_hex

NOFOLLOW = os.O_NOFOLLOW | os.O_NONBLOCK


@contextmanager
def open_directory(path: Path, parent_fd: int | None = None) -> Iterator[int]:
    """Open each directory component without following symlinks."""
    if parent_fd is not None:
        start, parts = path.name, ()
    elif path.anchor:
        start, parts = path.anchor, path.parts[1:]
    else:
        start, parts = ".", path.parts
    flags = os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW
    fd = os.open(start, flags, dir_fd=parent_fd)
    try:
        for part in parts:
            child_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child_fd
        yield fd
    finally:
        os.close(fd)


@contextmanager
def open_relative_directory(path: Path, root_fd: int) -> Iterator[int]:
    """Open a validated relative path from an existing directory descriptor."""
    with ExitStack() as stack:
        fd = root_fd
        for part in path.parts:
            fd = stack.enter_context(open_directory(Path(part), fd))
        yield fd


def directory_names(fd: int, limit: int, *, stop_at_limit: bool = False) -> list[str]:
    """Return sorted names with an extra entry to signal an exceeded limit."""
    with os.scandir(fd) as listing:
        names = (entry.name for entry in listing)
        if stop_at_limit:
            return sorted(islice(names, limit + 1))
        return nsmallest(limit + 1, names)


def entry_mode(path: Path, fd: int) -> int:
    mode = os.stat(path.name, dir_fd=fd, follow_symlinks=False).st_mode
    if stat.S_ISLNK(mode):
        raise ValueError("symlink is not allowed")
    return mode


def _check_file(info: os.stat_result, limit: int, size_error: str) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("symlink is not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("expected a regular file")
    if info.st_size > limit:
        raise ValueError(size_error)


def read_text(
    path: Path,
    limit_mib: int,
    *,
    dir_fd: int | None = None,
    normalize_newlines: bool = True,
) -> str:
    return _read_text(path, limit_mib * 1024 * 1024, f"{limit_mib} MiB", dir_fd, normalize_newlines)


def read_text_kib(path: Path, limit_kib: int, *, dir_fd: int | None = None) -> str:
    return _read_text(path, limit_kib * 1024, f"{limit_kib} KiB", dir_fd)


def _read_text(
    path: Path, limit: int, label: str, dir_fd: int | None, normalize_newlines: bool = True
) -> str:
    target = path if dir_fd is None else path.name
    size_error = f"file exceeds the {label} limit"
    _check_file(os.stat(target, dir_fd=dir_fd, follow_symlinks=False), limit, size_error)
    fd = os.open(target, os.O_RDONLY | NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as stream:
        _check_file(os.fstat(stream.fileno()), limit, size_error)
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(size_error)
    text = data.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n") if normalize_newlines else text


def write_new_text(path: Path, text: str, *, dir_fd: int | None = None) -> None:
    """Publish a bounded UTF-8 file exclusively, after writing it in full."""
    data = text.encode("utf-8")
    if len(data) > 1024 * 1024:
        raise ValueError("file exceeds the 1 MiB limit")
    if dir_fd is None:
        with open_directory(path.parent) as fd:
            _publish(path.name, data, fd)
    else:
        _publish(path.name, data, dir_fd)


def _publish(name: str, data: bytes, directory: int) -> None:
    temp = f".research-{token_hex(16)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW
    fd = os.open(temp, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.link(temp, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    finally:
        os.unlink(temp, dir_fd=directory)
