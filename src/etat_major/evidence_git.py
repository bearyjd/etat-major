"""Collect bounded progress facts from local Git metadata."""

import re
import subprocess
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from etat_major.evidence_records import (
    OID_PATTERN,
    PullRequest,
    Release,
    branch_task,
    resolve_task_keys,
)
from etat_major.localfiles import open_directory
from etat_major.renames import _git_result, _guard_config, _inspect_metadata
from etat_major.taskfile import TaskFileError

_OUTPUT_LIMIT = 16 * 1024 * 1024
_OID = re.compile(OID_PATTERN)
_HEADS = "refs/heads/"


@dataclass(frozen=True)
class GitEvidence:
    commits: Mapping[str, tuple[str, ...]]
    trailers: Mapping[str, tuple[str, ...]]
    heads: Mapping[str, str]
    default_commits: frozenset[str]
    files: frozenset[str] | None
    releases: Mapping[str, tuple[str, ...]]


def _read(
    fd: int, args: tuple[str, ...], *, limit: int = _OUTPUT_LIMIT, missing_ok: bool = False
) -> str:
    output, _ = _git_result(fd, args, limit, exit_codes=(0, 1) if missing_ok else (0,))
    return output.decode("utf-8", errors="surrogateescape")


def _oids(values: Iterable[str]) -> frozenset[str]:
    oids = frozenset(values)
    if any(not _OID.fullmatch(oid) for oid in oids):
        raise ValueError("invalid commit id in Git output")
    return oids


def _log(fd: int) -> dict[str, tuple[str, ...]]:
    data = _read(
        fd,
        (
            "log",
            "--all",
            "--no-notes",
            "--no-show-signature",
            "--no-decorate",
            "-z",
            "--format=%H%x00%(trailers:key=Task,valueonly,unfold,separator=%x0a)",
            "--",
        ),
    )
    fields = data.split("\0")
    if fields.pop() or len(fields) % 2:
        raise ValueError("invalid Git log output")
    commits = dict(zip(fields[::2], fields[1::2], strict=True))
    _oids(commits)
    return {oid: resolve_task_keys(trailers=tuple(raw.split("\n"))) for oid, raw in commits.items()}


def _heads(fd: int) -> dict[str, str]:
    raw = _read(fd, ("for-each-ref", "--format=%(objectname)%00%(refname:strip=2)", _HEADS))
    heads = {}
    for row in raw.split("\n"):
        if row:
            oid, sep, name = row.partition("\0")
            if not sep or not _OID.fullmatch(oid) or not name:
                raise ValueError("invalid Git branch output")
            heads[name] = oid
    return heads


def _resolve_commit(fd: int, ref: str) -> str | None:
    raw = _read(
        fd,
        ("rev-parse", "--quiet", "--verify", "--end-of-options", f"{ref}^{{commit}}"),
        limit=128,
        missing_ok=True,
    )
    if not raw:
        return None
    oid = raw.removesuffix("\n")
    if not _OID.fullmatch(oid):
        raise ValueError("invalid commit id in Git output")
    return oid


def _default_tip(fd: int, heads: Mapping[str, str]) -> str | None:
    remote_head = _resolve_commit(fd, "refs/remotes/origin/HEAD")
    if remote_head is not None:
        return remote_head
    candidates = {name for name in heads if not name.startswith("task/")}
    conventional = {"main", "master"} & candidates
    choices = conventional or candidates
    return heads[next(iter(choices))] if len(choices) == 1 else None


def _branch_commits(
    fd: int,
    heads: Mapping[str, str],
    default: str | None,
    all_commits: Mapping[str, tuple[str, ...]],
    known: frozenset[str],
) -> Mapping[str, tuple[str, ...]]:
    inferred: dict[str, set[str]] = defaultdict(set)
    for branch, oid in heads.items():
        if not (key := branch_task(branch, known)):
            continue
        if default:
            raw = _read(fd, ("rev-list", oid, "--not", default, "--"))
            commits = _oids(raw.splitlines())
        else:
            commits = (oid,)
        for commit in commits:
            inferred[commit].add(key)
    return MappingProxyType(
        {oid: keys or tuple(sorted(inferred.get(oid, ()))) for oid, keys in all_commits.items()}
    )


def _release_matches(
    fd: int, releases: tuple[Release, ...], merges: set[str]
) -> Mapping[str, tuple[str, ...]]:
    if not merges:
        return MappingProxyType({})
    tags = {}
    for release in releases:
        if release.published_at is not None:
            if tip := _resolve_commit(fd, f"refs/tags/{release.tag}"):
                tags[release.tag] = tip
    shipped = {}
    for merge in sorted(merges):
        if _resolve_commit(fd, merge) != merge:
            continue
        shipped[merge] = tuple(
            name
            for name, tip in sorted(tags.items())
            if _git_result(fd, ("merge-base", "--is-ancestor", merge, tip), 128, exit_codes=(0, 1))[
                1
            ]
            == 0
        )
    return MappingProxyType(shipped)


def _tracked_files(fd: int, head: str | None) -> frozenset[str] | None:
    if head is None:
        return None
    raw = _read(fd, ("ls-tree", "-r", "-z", head, "--"))
    paths = set()
    for entry in raw.split("\0"):
        if entry:
            meta, sep, path = entry.partition("\t")
            if not sep:
                raise ValueError("invalid Git tree output")
            if meta.startswith(("100644 blob ", "100755 blob ")):
                paths.add(path)
    return frozenset(paths)


def _collect(
    fd: int, prs: tuple[PullRequest, ...], releases: tuple[Release, ...], known: frozenset[str]
) -> GitEvidence:
    heads = _heads(fd)
    default = _default_tip(fd, heads)
    default_commits = (
        _oids(_read(fd, ("rev-list", default, "--")).splitlines()) if default else frozenset()
    )
    log = _log(fd)
    merges = {pr.merge_commit.oid for pr in prs if pr.state == "MERGED" and pr.merge_commit}
    return GitEvidence(
        commits=_branch_commits(fd, heads, default, log, known),
        trailers=MappingProxyType(log),
        heads=MappingProxyType(heads),
        default_commits=default_commits,
        files=_tracked_files(fd, _resolve_commit(fd, "HEAD")),
        releases=_release_matches(fd, releases, merges),
    )


def load_git(
    repo: Path, prs: tuple[PullRequest, ...], releases: tuple[Release, ...], known: frozenset[str]
) -> GitEvidence:
    metadata = repo / ".git"
    try:
        with open_directory(metadata) as fd:
            try:
                _inspect_metadata(fd)
                _guard_config(fd)
            except ValueError as exc:
                raise TaskFileError(metadata, "metadata", str(exc)) from None
            try:
                return _collect(fd, prs, releases, known)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise TaskFileError(
                    metadata, "history", "cannot read bounded local Git history"
                ) from None
    except (OSError, RecursionError, subprocess.TimeoutExpired):
        raise TaskFileError(metadata, "metadata", "cannot open local Git directory") from None
