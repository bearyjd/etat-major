"""Read bounded regular files without following the final path component."""

import os
import stat
from pathlib import Path

NOFOLLOW = os.O_NOFOLLOW | os.O_NONBLOCK


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
