"""Load an intent workspace (``research/``, ``decisions/``, ``features/<project>/``).

File and cross-file problems are counted, with the first 200 retained as ``Issue`` objects.
Unresolved references are reported as ``missing`` rather than raised.
"""

from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

from etat_major.localfiles import NOFOLLOW
from etat_major.records import (
    Decision,
    Feature,
    ResearchArtifact,
    load_decision,
    load_feature,
    load_research,
)
from etat_major.refs import Ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import bounded_repr

_ISSUE_LIMIT = 200
_DIRECTORY_LIMIT = 2000


@dataclass(frozen=True)
class Issue:
    """A problem in a file (``path`` is workspace-relative) or in a record (``path`` is its ref)."""

    path: str
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.path}: field '{self.field}'" if self.field else self.path
        return f"{where}: {self.message}"


class _IssueLog:
    def __init__(self) -> None:
        self.issues: list[Issue] = []
        self.omitted = 0

    def append(self, issue: Issue) -> None:
        if len(self.issues) < _ISSUE_LIMIT:
            self.issues.append(issue)
        else:
            self.omitted += 1


@dataclass(frozen=True)
class Workspace:
    research: tuple[ResearchArtifact, ...]
    decisions: tuple[Decision, ...]
    features: tuple[Feature, ...]
    issues: tuple[Issue, ...]
    warnings: tuple[Issue, ...] = ()
    omitted_issues: int = 0

    def get_research(self, record_id: str) -> ResearchArtifact | None:
        return next((r for r in self.research if r.id == record_id), None)

    def get_decision(self, record_id: str) -> Decision | None:
        return next((d for d in self.decisions if d.id == record_id), None)

    def get_feature(self, project: str, record_id: str) -> Feature | None:
        return next((f for f in self.features if (f.project, f.id) == (project, record_id)), None)

    def get_feature_by_ref(self, ref: Ref) -> Feature | None:
        return self.get_feature(ref.project or "", ref.id)


def feature_ref(feature: Feature) -> Ref:
    return Ref("feature", feature.id, project=feature.project)


def linked_decisions(ws: Workspace, feature: Feature) -> tuple[Decision, ...]:
    """Decisions the feature lists, plus decisions that list the feature."""
    me = feature_ref(feature)
    listed = {d.id for d in feature.decisions}
    return tuple(d for d in ws.decisions if d.id in listed or me in d.features)


class WorkspaceError(ValueError):
    """The workspace root cannot be opened as a directory."""


def _check_path(path: Path, fd: int) -> int:
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("symlink is not allowed")
    return info.st_mode


@contextmanager
def _directory(path: Path, parent_fd: int | None = None) -> Iterator[int]:
    target = path if parent_fd is None else path.name
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=parent_fd)
    try:
        yield fd
    finally:
        os.close(fd)


def _issue(root: Path, path: Path, exc: OSError | ValueError | RuntimeError) -> Issue:
    message = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
    return Issue(path.relative_to(root).as_posix(), None, message)


def _entries(root: Path, base: Path, fd: int, issues: _IssueLog) -> Iterator[tuple[Path, int]]:
    try:
        with os.scandir(fd) as entries:
            names = [entry.name for entry in islice(entries, _DIRECTORY_LIMIT + 1)]
    except OSError as exc:
        issues.append(_issue(root, base, exc))
        return
    if len(names) > _DIRECTORY_LIMIT:
        names.pop()
        issues.append(
            Issue(
                base.relative_to(root).as_posix(),
                None,
                f"directory exceeds {_DIRECTORY_LIMIT} entries",
            )
        )
    for name in sorted(names):
        path = base / name
        try:
            mode = _check_path(path, fd)
        except (OSError, ValueError) as exc:
            issues.append(_issue(root, path, exc))
            continue
        yield path, mode


def _walk_markdown(
    root: Path, base: Path, fd: int, issues: _IssueLog, *, allow_projects: bool
) -> Iterator[tuple[Path, int]]:
    for path, mode in _entries(root, base, fd, issues):
        if stat.S_ISDIR(mode):
            if not allow_projects:
                issues.append(
                    Issue(path.relative_to(root).as_posix(), None, "unexpected directory")
                )
                continue
            try:
                with _directory(path, fd) as child_fd:
                    yield from _walk_markdown(root, path, child_fd, issues, allow_projects=False)
            except OSError as exc:
                issues.append(_issue(root, path, exc))
        elif path.name.endswith(".md"):
            if stat.S_ISREG(mode):
                yield path, fd
            else:
                issues.append(
                    Issue(path.relative_to(root).as_posix(), None, "expected a regular file")
                )


def _load_dir[T](
    root: Path, root_fd: int, sub: str, loader: Callable[..., T], issues: _IssueLog
) -> list[T]:
    base = root / sub
    try:
        mode = _check_path(base, root_fd)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        issues.append(_issue(root, base, exc))
        return []
    if not stat.S_ISDIR(mode):
        issues.append(Issue(sub, None, "expected a directory"))
        return []
    out: list[T] = []
    try:
        with _directory(base, root_fd) as fd:
            for path, folder_fd in _walk_markdown(
                root, base, fd, issues, allow_projects=sub == "features"
            ):
                rel = path.relative_to(root)
                if sub == "features" and len(rel.parts) != 3:
                    issues.append(
                        Issue(rel.as_posix(), None, "expected features/<project>/<file>.md")
                    )
                    continue
                try:
                    out.append(loader(path, dir_fd=folder_fd))
                except TaskFileError as exc:
                    issues.append(Issue(rel.as_posix(), exc.field, exc.message))
    except OSError as exc:
        issues.append(_issue(root, base, exc))
    return out


def _load_feature(path: Path, *, dir_fd: int) -> Feature:
    feature = load_feature(path, dir_fd=dir_fd)
    if feature.project != path.parent.name:
        raise TaskFileError(
            path,
            "project",
            f"project {bounded_repr(feature.project)} does not match "
            f"directory {bounded_repr(path.parent.name)}",
        )
    return feature


def _duplicates(records: list[Ref], issues: _IssueLog) -> None:
    for ref, n in sorted(Counter(records).items(), key=lambda kv: str(kv[0])):
        if n > 1:
            issues.append(
                Issue(str(ref), "id", f"duplicate id: {n} records share {bounded_repr(str(ref))}")
            )


def _missing(owner: Ref, field: str, ref: Ref) -> Issue:
    return Issue(
        str(owner), field, f"missing: {bounded_repr(str(ref))} does not resolve to a record"
    )


def _has_research_ref(ws: Workspace, ref: Ref) -> bool:
    research = ws.get_research(ref.id)
    return research is not None and (
        ref.fragment is None or any(f.id == ref.fragment for f in research.findings)
    )


def _check_decision(ws: Workspace, d: Decision) -> Iterator[Issue]:
    owner = Ref("decision", d.id)
    for ref in d.evidence:
        if not _has_research_ref(ws, ref):
            yield _missing(owner, "evidence", ref)
    for ref in d.features:
        if not ws.get_feature_by_ref(ref):
            yield _missing(owner, "features", ref)


def _check_feature(ws: Workspace, f: Feature) -> Iterator[Issue]:
    owner = feature_ref(f)
    for ref in f.research:
        if not _has_research_ref(ws, ref):
            yield _missing(owner, "research", ref)
    for ref in f.decisions:
        if not ws.get_decision(ref.id):
            yield _missing(owner, "decisions", ref)
    if f.status == "planned" and not any(d.status == "approved" for d in linked_decisions(ws, f)):
        yield Issue(
            str(owner),
            "status",
            "status 'planned' requires a linked Decision with status approved",
        )


def _cross_validate(ws: Workspace, issues: _IssueLog) -> None:
    _duplicates([Ref("research", r.id) for r in ws.research], issues)
    _duplicates([Ref("decision", d.id) for d in ws.decisions], issues)
    _duplicates([feature_ref(f) for f in ws.features], issues)
    for d in ws.decisions:
        for issue in _check_decision(ws, d):
            issues.append(issue)
    for f in ws.features:
        for issue in _check_feature(ws, f):
            issues.append(issue)


def link_warnings(ws: Workspace, feature: Feature) -> tuple[Issue, ...]:
    owner = feature_ref(feature)
    listed = {d.id for d in feature.decisions}
    warnings: list[Issue] = []
    for decision in linked_decisions(ws, feature):
        decision_ref = Ref("decision", decision.id)
        message = (
            f"one-sided link between {bounded_repr(str(owner))} and "
            f"{bounded_repr(str(decision_ref))}"
        )
        if decision.id not in listed:
            warnings.append(Issue(str(owner), "decisions", message))
        elif owner not in decision.features:
            warnings.append(Issue(str(decision_ref), "features", message))
    return tuple(warnings)


def load_workspace(root: Path) -> Workspace:
    issues = _IssueLog()
    try:
        mode = root.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("symlink is not allowed")
        if not stat.S_ISDIR(mode):
            raise ValueError("is not a directory")
        with _directory(root) as fd:
            resolved = root.resolve(strict=True)
            if not os.path.samestat(resolved.lstat(), os.fstat(fd)):
                raise ValueError("workspace directory changed while opening")
            research = _load_dir(resolved, fd, "research", load_research, issues)
            decisions = _load_dir(resolved, fd, "decisions", load_decision, issues)
            features = _load_dir(resolved, fd, "features", _load_feature, issues)
    except (OSError, ValueError, RuntimeError) as exc:
        detail = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
        raise WorkspaceError(f"workspace {bounded_repr(str(root))}: {detail}") from exc
    ws = Workspace(tuple(research), tuple(decisions), tuple(features), ())
    _cross_validate(ws, issues)
    warnings = tuple(w for feature in ws.features for w in link_warnings(ws, feature))
    return Workspace(
        ws.research, ws.decisions, ws.features, tuple(issues.issues), warnings, issues.omitted
    )
