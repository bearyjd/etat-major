"""Open symlink-free directories and read bounded regular files."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
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


def _check_file(info: os.stat_result, limit_mib: int) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("symlink is not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("expected a regular file")
    if info.st_size > limit_mib * 1024 * 1024:
        raise ValueError(f"file exceeds the {limit_mib} MiB limit")


def read_text(path: Path, limit_mib: int, *, dir_fd: int | None = None) -> str:
    target = path if dir_fd is None else path.name
    _check_file(os.stat(target, dir_fd=dir_fd, follow_symlinks=False), limit_mib)
    fd = os.open(target, os.O_RDONLY | NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as stream:
        _check_file(os.fstat(stream.fileno()), limit_mib)
        limit = limit_mib * 1024 * 1024
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"file exceeds the {limit_mib} MiB limit")
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")


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
