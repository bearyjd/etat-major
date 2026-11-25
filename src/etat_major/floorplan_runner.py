"""Run a pinned deterministic Floorplan step in a caller-supplied disposable copy."""

import json
import os
import selectors
import shutil
import signal
import subprocess
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Any

from etat_major.floorplan import FLOORPLAN_COMMIT, FloorplanIndex, load_graph
from etat_major.floorplan_runner_files import (
    artifact_stamp,
    discovery_repository,
    guard_copy,
)
from etat_major.floorplan_runner_files import (
    bundle_digest as _bundle_digest,
)
from etat_major.floorplan_runner_files import (
    relative_file as _relative,
)
from etat_major.git_hardening import config_environment
from etat_major.localfiles import open_directory, read_text
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import safe

_OPERATIONS = {
    "scan": (),
    "build": (),
    "refresh": ("--from-code",),
}
_BUNDLE_DIGEST = "c4d75c09f3106e56deece38abbf6b2875cb74522539c8ae1d5076043da8f7a2d"
_SCAN = Path("floorplan/.cache/scan.json")
_ARCHITECTURE = Path("floorplan/architecture.json")
_GRAPH = Path("floorplan/graph.json")
_CHANGES = Path("floorplan/.cache/changes.json")
_FILE_LIMIT_MIB = 64
_COPY_ENTRIES = 25_000
_OUTPUT_LIMIT = 1024 * 1024
_TIMEOUT = 60
_CLEANUP_TIMEOUT = 1


@dataclass(frozen=True)
class FloorplanRun:
    artifact: str
    renames: tuple[tuple[str, str], ...] = ()
    retained_nodes: int | None = None
    previous_nodes: int | None = None


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate JSON key")
    return values


def _invalid_constant(_: str) -> None:
    raise ValueError("invalid JSON number")


def _json_object(raw: str | bytes, path: Path) -> dict:
    try:
        result = json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        if isinstance(result, dict):
            return result
    except (ValueError, RecursionError):
        pass
    raise TaskFileError(path, "JSON", "expected a valid JSON object with unique keys")


def _read_object(copy: Path, path: Path) -> dict:
    absolute = copy / path
    try:
        with open_directory(absolute.parent) as fd:
            text = read_text(absolute, _FILE_LIMIT_MIB, dir_fd=fd)
    except (OSError, ValueError):
        raise TaskFileError(path, "file", "expected a bounded, symlink-free UTF-8 file") from None
    return _json_object(text, path)


def _rows(data: object, path: Path, field: str) -> list[dict]:
    if (
        not isinstance(data, list)
        or len(data) > _COPY_ENTRIES
        or any(not isinstance(row, dict) for row in data)
    ):
        raise TaskFileError(path, field, "expected a bounded list of objects")
    return data


def _scan_cache(copy: Path) -> None:
    scan = _read_object(copy, _SCAN)
    if (
        type(scan.get("version")) is not int
        or scan["version"] != 1
        or scan.get("root") != str(copy)
        or scan.get("blueprint")
    ):
        raise TaskFileError(_SCAN, "version", "expected a v1 code scan from this copy")
    repos = _rows(scan.get("repos"), _SCAN, "repos")
    if (
        len(repos) != 1
        or repos[0].get("path") != "."
        or repos[0].get("remote", False) is not None
        or "worktreeOf" in repos[0]
    ):
        raise TaskFileError(_SCAN, "repos", "expected only the private root repository")
    for row in _rows(scan.get("files"), _SCAN, "files"):
        if not _relative(row.get("path")) or row.get("repo") != ".":
            raise TaskFileError(
                _SCAN, "files", "expected relative files in the private root repository"
            )
    for row in _rows(scan.get("routes"), _SCAN, "routes"):
        if not _relative(row.get("file")) or (
            row.get("wrapFile") is not None and not _relative(row["wrapFile"])
        ):
            raise TaskFileError(_SCAN, "routes", "expected relative route source paths")


def _graph(copy: Path) -> FloorplanIndex:
    try:
        return load_graph(copy / _GRAPH)
    except TaskFileError:
        raise TaskFileError(
            _GRAPH, "graph", "expected a valid floorplan/graph@1 artifact"
        ) from None


def _renames(
    copy: Path, before: FloorplanIndex, after: FloorplanIndex
) -> tuple[tuple[str, str], ...]:
    changes = _read_object(copy, _CHANGES)
    files = changes.get("files")
    rows = _rows(files.get("moved") if isinstance(files, dict) else None, _CHANGES, "files.moved")
    removed = before.file_paths - after.file_paths
    added = after.file_paths - before.file_paths
    old_paths, new_paths = set(), set()
    result = []
    for row in rows:
        old, new = row.get("from"), row.get("to")
        if (
            not _relative(old)
            or not _relative(new)
            or old not in removed
            or new not in added
            or old in old_paths
            or new in new_paths
        ):
            raise TaskFileError(_CHANGES, "files.moved", "expected distinct verified rename paths")
        old_paths.add(old)
        new_paths.add(new)
        result.append((old, new))
    return tuple(sorted(result))


def _node(copy: Path, source: Path) -> Path:
    supplied = shutil.which("node")
    if supplied is None:
        raise TaskFileError(Path("floorplan"), "node", "trusted Node executable missing from PATH")
    candidate = Path(os.path.abspath(supplied))
    try:
        runtime = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise TaskFileError(Path("floorplan"), "node", "cannot resolve Node executable") from None
    if any(path.is_relative_to(root) for path in (candidate, runtime) for root in (copy, source)):
        raise TaskFileError(Path("floorplan"), "node", "expected Node outside the copy and bundle")
    return runtime


def _read_output(process: subprocess.Popen, deadline: float) -> bytes:
    stdout = bytearray()
    size = 0
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ)
        while selector.get_map():
            time_left = deadline - monotonic()
            if time_left <= 0 or not (events := selector.select(time_left)):
                raise ValueError("Floorplan step timed out")
            for event, _ in events:
                chunk = os.read(event.fd, 16_384)
                if not chunk:
                    selector.unregister(event.fileobj)
                    continue
                size += len(chunk)
                if size > _OUTPUT_LIMIT:
                    raise ValueError("Floorplan step exceeded its output limit")
                if event.data is stdout:
                    stdout.extend(chunk)
    return bytes(stdout)


def _environment(copy: Path, repository: Path) -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": os.devnull,
        "LC_ALL": "C.UTF-8",
        "DO_NOT_TRACK": "1",
        "FLOORPLAN_UNATTENDED": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_CEILING_DIRECTORIES": str(copy.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DIR": str(repository),
        "GIT_COMMON_DIR": str(repository),
        "GIT_WORK_TREE": str(copy),
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        **config_environment(),
    }


def _observe_exit(pid: int, deadline: float) -> None:
    while not os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ValueError("Floorplan step timed out")
        sleep(min(0.01, remaining))


def _signal_group(pid: int) -> list[str]:
    # A reaped leader could have its PID reused before group cleanup.
    try:
        exited = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return []
    except OSError:
        return ["could not verify the Floorplan process group"]
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return []
    except OSError:
        notes = ["could not signal the Floorplan process group"]
        if exited is None:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                notes.append("could not signal Floorplan directly")
        return notes
    return []


def _finish_process(
    process: subprocess.Popen, operation: str, failure: BaseException | None = None
) -> None:
    notes = _signal_group(process.pid)
    try:
        status = process.wait(timeout=_CLEANUP_TIMEOUT)
    except subprocess.TimeoutExpired:
        status = None
        notes.append("could not reap Floorplan within the cleanup timeout")
    except OSError:
        status = None
        notes.append("could not reap Floorplan")
    if failure is not None:
        for note in notes:
            failure.add_note(note)
        return
    if status not in (None, 0):
        raise TaskFileError(Path("floorplan"), operation, "Floorplan step failed")
    if notes:
        raise TaskFileError(Path("floorplan"), operation, ". ".join(notes))


def _supervise(process: subprocess.Popen, operation: str, deadline: float) -> bytes:
    try:
        try:
            output = _read_output(process, deadline)
            _observe_exit(process.pid, deadline)
        except OSError:
            raise TaskFileError(Path("floorplan"), operation, "could not read Floorplan") from None
        except ValueError as exc:
            raise TaskFileError(Path("floorplan"), operation, str(exc)) from None
    except BaseException as failure:
        _finish_process(process, operation, failure)
        raise
    _finish_process(process, operation)
    return output


def _invoke(operation: str, node: Path, bundle: Path, copy: Path, repository: Path) -> None:
    command = (
        str(node),
        str(bundle / "scripts" / f"{operation}.mjs"),
        str(copy),
        *_OPERATIONS[operation],
        "--json",
        "--unattended",
    )
    deadline = monotonic() + _TIMEOUT
    try:
        process = subprocess.Popen(  # noqa: S603 - verified script and fixed arguments
            command,
            cwd=copy,
            env=_environment(copy, repository),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, ValueError):
        raise TaskFileError(Path("floorplan"), operation, "could not start Floorplan") from None
    try:
        stdout = _supervise(process, operation, deadline)
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    result = _json_object(stdout, Path("floorplan"))
    if result.get("schema") != f"floorplan/{operation}-result@1" or result.get("ok") is not True:
        raise TaskFileError(Path("floorplan"), operation, "unexpected Floorplan response")


def _mountinfo() -> Path:
    return Path("/proc") / str(os.getpid()) / "mountinfo"


def _output_paths(operation: str) -> tuple[Path, ...]:
    return {"scan": (_SCAN,), "build": (_GRAPH,), "refresh": (_SCAN, _GRAPH, _CHANGES)}[operation]


def run_floorplan(operation: str, copy: Path, source: Path) -> FloorplanRun:
    if operation not in _OPERATIONS:
        raise TaskFileError(Path("floorplan"), "operation", "expected scan, build or refresh")
    copy, source = copy.absolute(), source.absolute()
    if (
        "//" in (copy.anchor, source.anchor)
        or ".." in (*copy.parts, *source.parts)
        or ":" in str(copy)
        or copy.is_relative_to(source)
        or source.is_relative_to(copy)
    ):
        raise TaskFileError(
            Path("floorplan"), "copy", "expected separate copy and source directories"
        )
    bundle = source / "skills" / "floorplan"
    try:
        verified = _bundle_digest(bundle) == _BUNDLE_DIGEST
    except (OSError, ValueError):
        verified = False
    if not verified:
        raise TaskFileError(
            Path("floorplan"), "source", f"expected pinned Floorplan {FLOORPLAN_COMMIT}"
        )
    guard_copy(copy, _mountinfo(), _COPY_ENTRIES, _FILE_LIMIT_MIB)
    if operation != "scan":
        _read_object(copy, _ARCHITECTURE)
    if operation == "build":
        _scan_cache(copy)
    before = _graph(copy) if operation == "refresh" else None
    outputs = _output_paths(operation)
    previous = {path: artifact_stamp(copy, path) for path in outputs}
    with discovery_repository(copy) as repository:
        _invoke(operation, _node(copy, source), bundle, copy, repository)
    for path in outputs:
        current = artifact_stamp(copy, path)
        if current is None or current == previous[path]:
            raise TaskFileError(path, "file", "Floorplan did not refresh the expected artifact")
    if operation == "scan":
        _scan_cache(copy)
        return FloorplanRun(_SCAN.as_posix())
    after = _graph(copy)
    if before is None:
        return FloorplanRun(_GRAPH.as_posix())
    _scan_cache(copy)
    return FloorplanRun(
        _GRAPH.as_posix(),
        _renames(copy, before, after),
        len(before.node_ids & after.node_ids),
        len(before.node_ids),
    )


def floorplan_parser(parser: ArgumentParser) -> None:
    parser.add_argument("action", choices=tuple(_OPERATIONS))
    parser.add_argument(
        "--copy", type=Path, required=True, help="disposable copy without Git metadata"
    )
    parser.add_argument("--source", type=Path, required=True, help="pinned Floorplan source tree")


def run_floorplan_cli(args: Namespace) -> int:
    result = run_floorplan(args.action, args.copy, args.source)
    print(f"Recorded {result.artifact}")
    if result.retained_nodes is not None:
        print(f"{result.retained_nodes} of {result.previous_nodes} Floorplan node IDs retained")
    for old, new in result.renames:
        print(f"{safe(old)} -> {safe(new)}")
    return 0
