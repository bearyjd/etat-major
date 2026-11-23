"""Bounded filesystem checks for the local Floorplan runner."""

import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unicodedata import normalize

from etat_major.component_paths import component_file_path
from etat_major.localfiles import (
    NOFOLLOW,
    directory_names,
    open_directory,
    open_relative_directory,
    read_text,
    write_new_text,
)
from etat_major.taskfile import TaskFileError

_BUNDLE_ENTRIES = 256
_BUNDLE_FILE_LIMIT = 4 * 1024 * 1024
_DEPTH_LIMIT = 32
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def _files(
    fd: int, prefix: Path, budget: list[int], device: int, *, depth: int = 0
) -> Iterator[tuple[Path, os.stat_result]]:
    if depth > _DEPTH_LIMIT:
        raise ValueError("directory depth exceeds its limit")
    names = directory_names(fd, budget[0], stop_at_limit=True)
    if len(names) > budget[0]:
        raise ValueError("directory entries exceed their limit")
    budget[0] -= len(names)
    for name in names:
        if name == ".git":
            raise ValueError("expected a copy without Git metadata")
        path = prefix / name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if info.st_dev != device:
            raise ValueError("mounted entry is not allowed")
        if stat.S_ISDIR(info.st_mode):
            with open_directory(Path(name), fd) as child:
                yield from _files(child, path, budget, device, depth=depth + 1)
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            yield path, info
        else:
            raise ValueError("expected regular files without symlinks or hard links")


def _file_digest(root_fd: int, path: Path) -> bytes:
    with open_relative_directory(path.parent, root_fd) as fd:
        infile = os.open(path.name, os.O_RDONLY | NOFOLLOW, dir_fd=fd)
        with os.fdopen(infile, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("expected a regular bundle file")
            data = stream.read(_BUNDLE_FILE_LIMIT + 1)
    if len(data) > _BUNDLE_FILE_LIMIT:
        raise ValueError("bundle file exceeds its size limit")
    return sha256(data).digest()


def bundle_digest(bundle: Path) -> str:
    digest = sha256()
    budget = [_BUNDLE_ENTRIES]
    with open_directory(bundle) as fd:
        paths = []
        for folder in ("assets", "scripts"):
            with open_directory(Path(folder), fd) as directory:
                paths.extend(
                    path for path, _ in _files(directory, Path(folder), budget, os.fstat(fd).st_dev)
                )
        for path in sorted(paths, key=lambda item: item.as_posix()):
            digest.update(os.fsencode(path) + b"\0" + _file_digest(fd, path))
    return digest.hexdigest()


def guard_copy(copy: Path, mountinfo: Path, entry_limit: int, file_limit_mib: int) -> None:
    try:
        with open_directory(copy) as fd:
            _check_mounts(copy, mountinfo)
            for path, info in _files(fd, Path(), [entry_limit], os.fstat(fd).st_dev):
                if not relative_file(path.as_posix()):
                    raise ValueError("copy contains an unsupported repository-relative path")
                if info.st_size > file_limit_mib * 1024 * 1024:
                    raise ValueError("copy file exceeds its size limit")
    except OSError:
        raise TaskFileError(Path("floorplan"), "copy", "cannot open a symlink-free copy") from None
    except ValueError as exc:
        raise TaskFileError(Path("floorplan"), "copy", str(exc)) from None


def relative_file(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 1024:
        return False
    try:
        component_file_path(value)
        component_file_path(normalize("NFKC", value))
    except ValueError:
        return False
    return True


def _check_mounts(copy: Path, mountinfo: Path) -> None:
    try:
        with open_directory(mountinfo.parent) as fd:
            text = read_text(mountinfo, 1, dir_fd=fd, normalize_newlines=False)
    except (OSError, ValueError):
        raise ValueError("could not verify the Linux mount table") from None
    for line in text.removesuffix("\n").split("\n"):
        fields = line.split(" ")
        if len(fields) < 6 or " - " not in line:
            raise ValueError("could not verify the Linux mount table")
        path = Path(_MOUNT_ESCAPE.sub(lambda match: chr(int(match[1], 8)), fields[4]))
        if path.is_relative_to(copy):
            raise ValueError("mounted copy or mounted entry is not allowed")


def artifact_stamp(copy: Path, path: Path) -> tuple[int, int, int, int, int] | None:
    try:
        with open_directory(copy / path.parent) as fd:
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("expected a regular artifact")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise TaskFileError(path, "file", "expected a symlink-free regular artifact") from None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def discovery_repository(copy: Path) -> Iterator[Path]:
    """Give the pinned scanner full-depth discovery without importing repository metadata."""
    try:
        with TemporaryDirectory(prefix=".etat-floorplan-", dir=copy.parent) as scratch:
            repository = Path(scratch)
            with open_directory(repository) as fd:
                for directory in ("objects", "refs"):
                    os.mkdir(directory, mode=0o700, dir_fd=fd)
                write_new_text(Path("HEAD"), "ref: refs/heads/floorplan\n", dir_fd=fd)
                write_new_text(
                    Path("config"), "[core]\nrepositoryformatversion = 0\nbare = false\n", dir_fd=fd
                )
            with open_directory(copy) as fd, _discovery_marker(fd):
                yield repository
    except OSError:
        raise TaskFileError(
            Path("floorplan"), "copy", "could not manage private Git discovery"
        ) from None


@contextmanager
def _discovery_marker(fd: int) -> Iterator[None]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW
    marker = os.open(".git", flags, 0o600, dir_fd=fd)
    try:
        original = os.fstat(marker)
    finally:
        os.close(marker)
    try:
        yield
    finally:
        actual = os.stat(".git", dir_fd=fd, follow_symlinks=False)
        if not os.path.samestat(actual, original):
            raise TaskFileError(Path("floorplan"), "copy", "private Git discovery marker changed")
        os.unlink(".git", dir_fd=fd)
