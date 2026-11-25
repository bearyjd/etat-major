"""Record prs.json and releases.json with the GitHub CLI, for a person at a terminal.

Bounded by the capture-script exception in AGENTS.md and docs/contracts/progress-evidence.md:
fixed gh commands, no shell, allow-listed environment, confirmation of the resolved target.
Nothing under src/ may import or run this script.
"""

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from threading import Event, Timer
from urllib.parse import urlsplit

from etat_major.evidence_records import load_prs, load_releases
from etat_major.localfiles import open_directory, write_new_text
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import safe

CAP = 4 * 1024 * 1024
LIMIT = 1000
TIMEOUT = 60.0
REPO_NAME = re.compile(r"[\w.-]+/[\w.-]+")
ALLOWED = (
    "PATH", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "GH_CONFIG_DIR", "LANG", "LC_ALL",
)  # fmt: skip
PINNED = {
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "NO_COLOR": "1",
    "GH_PAGER": "cat",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}
REPO_ARGS = ("repo", "view", "--json", "nameWithOwner,url")
PR_FIELDS = (
    "number,title,body,state,isDraft,mergedAt,headRefName,reviewDecision,"
    "statusCheckRollup,mergeCommit"
)
PR_ARGS = ("pr", "list", "--state", "all", "--limit", str(LIMIT), "--json", PR_FIELDS)
RELEASE_ARGS = ("release", "list", "--limit", str(LIMIT), "--json", "tagName,publishedAt")
# name -> (gh arguments, loader that validates the recording)
TARGETS = {"prs.json": (PR_ARGS, load_prs), "releases.json": (RELEASE_ARGS, load_releases)}


class RecordError(Exception):
    """A refusal or failure, worded without remotes, absolute paths or tokens."""


def kill_group(proc: subprocess.Popen) -> None:
    """Kill gh and anything it started, so no grandchild can hold the pipe open."""
    with suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    return {**{k: environ[k] for k in ALLOWED if k in environ}, **PINNED}


def resolve_gh(environ: Mapping[str, str]) -> str:
    entries = environ.get("PATH", "").split(os.pathsep)
    if not environ.get("PATH") or any(not Path(e).is_absolute() for e in entries):
        raise RecordError("PATH must list only absolute directories")
    for entry in entries:
        candidate = Path(entry) / "gh"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RecordError("gh was not found on PATH")


def run_gh(
    gh: str,
    args: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    label: str = "gh",
) -> bytes:
    """Run gh once with stdin closed, stdout capped and stderr discarded."""
    try:
        proc = subprocess.Popen(  # noqa: S603
            [gh, *args],
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        raise RecordError(f"{label}: cannot start") from None
    expired: list[bool] = []
    read_done = Event()

    def on_timeout() -> None:
        # A timer that fires after gh exited and its output was read is not a timeout.
        if proc.poll() is None or not read_done.is_set():
            expired.append(True)
            kill_group(proc)

    timer = Timer(timeout, on_timeout)
    timer.start()
    try:
        data = proc.stdout.read(CAP + 1) if proc.stdout else b""
        read_done.set()
        if len(data) > CAP:
            kill_group(proc)
        status = proc.wait()
    finally:
        timer.cancel()
        kill_group(proc)
        proc.wait()
        if proc.stdout:
            proc.stdout.close()
    if len(data) > CAP:
        raise RecordError(f"{label}: output exceeds the 4 MiB limit")
    if not expired and status == 0:
        return data
    if expired:
        raise RecordError(f"{label}: timed out")
    raise RecordError(f"{label}: failed")


def describe_target(raw: bytes) -> tuple[str, str]:
    try:
        info = json.loads(raw)
        url, name = info["url"], info["nameWithOwner"]
        if not (isinstance(url, str) and isinstance(name, str) and REPO_NAME.fullmatch(name)):
            raise ValueError("unexpected repository description")
        return urlsplit(url).hostname or "", name
    except (ValueError, KeyError, TypeError, RecursionError):
        raise RecordError("gh repo view: unexpected output") from None


def validate(name: str, data: bytes, out: Path, directory: int) -> int:
    """Check the bytes with the report command's own loader via a private temp file."""
    args, loader = TARGETS[name]
    temp = f".{name}.{secrets.token_hex(8)}.check.tmp"
    try:
        text = data.decode("utf-8")
        write_new_text(Path(temp), text, dir_fd=directory, limit_bytes=CAP)
    except ValueError:
        raise RecordError(f"{name}: output is not bounded UTF-8 text") from None
    except OSError:
        raise RecordError(f"{name}: cannot create the check file") from None
    try:
        return len(loader(out / temp))
    except TaskFileError as exc:
        raise RecordError(
            f"{name}: field '{safe(exc.field_name, limit=80)}': {exc.message}"
        ) from None
    finally:
        os.unlink(temp, dir_fd=directory)


def publish(recordings: Mapping[str, bytes], directory: int) -> None:
    done: list[str] = []
    try:
        for name, data in recordings.items():
            write_new_text(Path(name), data.decode("utf-8"), dir_fd=directory, limit_bytes=CAP)
            done.append(name)
    except OSError:
        for name in done:
            os.unlink(name, dir_fd=directory)
        raise RecordError("could not create the output files") from None


def record(checkout: Path, out: Path, environ, confirm, timeout: float) -> None:
    gh, env = resolve_gh(environ), child_env(environ)
    host, repo = describe_target(run_gh(gh, REPO_ARGS, checkout, env, timeout))
    print(f"Target host: {safe(host, limit=128)}\nTarget repository: {safe(repo, limit=128)}")
    try:
        answer = confirm("Type 'yes' to record this repository: ")
    except EOFError:
        answer = ""
    if answer != "yes":
        raise RecordError("target not confirmed; nothing was written")
    fetched = {n: run_gh(gh, a, checkout, env, timeout, n) for n, (a, _) in TARGETS.items()}
    try:
        with open_directory(out) as directory:
            counts = {n: validate(n, data, out, directory) for n, data in fetched.items()}
            publish(fetched, directory)
    except OSError:
        raise RecordError("cannot use the output directory") from None
    for name, count in counts.items():
        if count >= LIMIT:
            print(
                f"warning: {name} has {count} entries and may be truncated at {LIMIT}",
                file=sys.stderr,
            )
        print(f"Wrote {name} ({count} entries)")


def check_arguments(
    checkout: Path, out: Path, environ: Mapping[str, str], interactive: bool
) -> None:
    if not interactive:
        raise RecordError("stdin must be an interactive terminal")
    for name in ("GH_HOST", "GH_REPO"):
        if name in environ:
            raise RecordError(f"refusing to run with {name} set")
    if not checkout.is_dir() or not out.is_dir():
        raise RecordError("the checkout and the output directory must exist")
    prefix = Path(out.anchor) if out.anchor else Path()
    for part in out.parts[1 if out.anchor else 0 :]:
        prefix = prefix / part
        if prefix.is_symlink():
            raise RecordError("the output directory must not be, or sit under, a symbolic link")
    clash = [n for n in TARGETS if os.path.lexists(out / n)]
    if clash:
        raise RecordError(f"{clash[0]} already exists in the output directory")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    interactive: bool | None = None,
    confirm: Callable[[str], str] = input,
    timeout: float = TIMEOUT,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path, help="checkout whose remote gh will query")
    parser.add_argument("out", type=Path, help="existing directory for prs.json and releases.json")
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    tty = sys.stdin.isatty() if interactive is None else interactive
    try:
        check_arguments(args.checkout, args.out, environ, tty)
        record(args.checkout.resolve(), args.out, environ, confirm, timeout)
    except RecordError as exc:
        print(f"record_github: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("record_github: interrupted; nothing was written", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
