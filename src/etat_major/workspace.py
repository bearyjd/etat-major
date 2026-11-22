"""Load research, decisions, features, and tasks from an intent workspace.

File and cross-file problems are counted, with the first 200 retained as ``Issue`` objects.
Unresolved references are reported as ``missing`` rather than raised.
"""

from __future__ import annotations

import errno
import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from heapq import nsmallest
from pathlib import Path

from etat_major.localfiles import open_directory as _directory
from etat_major.planning import Milestone, load_scoped_milestone, parse_vision
from etat_major.records import (
    Decision,
    Feature,
    ResearchArtifact,
    load_decision,
    load_feature,
    load_research,
)
from etat_major.refs import Ref
from etat_major.taskfile import Task, TaskFileError, parse_task
from etat_major.text_safety import bounded_repr, safe

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
        return safe(f"{where}: {self.message}")


class _IssueLog:
    def __init__(self, limit: int | None = _ISSUE_LIMIT) -> None:
        self.limit = limit
        self.issues: list[Issue] = []
        self.omitted = 0

    def append(self, issue: Issue) -> None:
        if self.limit is None or len(self.issues) < self.limit:
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
    tasks: tuple[Task, ...] = ()
    milestones: tuple[tuple[str, Milestone], ...] = ()

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


class WorkspaceError(TaskFileError):
    """The workspace root cannot be opened as a directory."""


def _check_path(path: Path, fd: int) -> int:
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("symlink is not allowed")
    return info.st_mode


def _issue(root: Path, path: Path, exc: OSError | ValueError | RuntimeError) -> Issue:
    message = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
    return Issue(path.relative_to(root).as_posix(), None, message)


def _entries(root: Path, base: Path, fd: int, issues: _IssueLog) -> Iterator[tuple[Path, int]]:
    try:
        with os.scandir(fd) as entries:
            names = nsmallest(_DIRECTORY_LIMIT + 1, (entry.name for entry in entries))
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
    for name in names:
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
    allow_projects = sub in {"features", "milestones", "tasks"}
    try:
        with _directory(base, root_fd) as fd:
            for path, folder_fd in _walk_markdown(
                root, base, fd, issues, allow_projects=allow_projects
            ):
                rel = path.relative_to(root)
                if allow_projects and len(rel.parts) != 3:
                    issues.append(
                        Issue(rel.as_posix(), None, f"expected {sub}/<project>/<file>.md")
                    )
                    continue
                try:
                    out.append(loader(path, dir_fd=folder_fd))
                except TaskFileError as exc:
                    issues.append(Issue(rel.as_posix(), exc.field_name, exc.message))
    except OSError as exc:
        issues.append(_issue(root, base, exc))
    return out


def _load_feature(path: Path, *, dir_fd: int) -> Feature:
    feature = load_feature(path, dir_fd=dir_fd)
    _check_project(path, feature.project)
    return feature


def _load_task(path: Path, *, dir_fd: int) -> tuple[str, Task]:
    task = parse_task(path, dir_fd=dir_fd)
    _check_project(path, task.project)
    return Path(*path.parts[-3:]).as_posix(), task


def _check_project(path: Path, project: str) -> None:
    if project != path.parent.name:
        raise TaskFileError(
            path,
            "project",
            f"project does not match directory {bounded_repr(path.parent.name)}",
        )


def _cyclic_components(graph: dict[str, list[str]]) -> list[list[str]]:
    """Find strongly connected components with iterative Kosaraju traversal."""
    reverse: dict[str, list[str]] = {node: [] for node in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].append(source)

    visited: set[str] = set()
    finished: list[str] = []
    for start in graph:
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(graph[start]))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                finished.append(node)
                stack.pop()
            elif child not in visited:
                visited.add(child)
                stack.append((child, iter(graph[child])))

    components: list[list[str]] = []
    visited.clear()
    for start in reversed(finished):
        if start in visited:
            continue
        component = [start]
        visited.add(start)
        for node in component:
            for parent in reverse[node]:
                if parent not in visited:
                    visited.add(parent)
                    component.append(parent)
        if len(component) > 1 or start in graph[start]:
            components.append(sorted(component))
    return sorted(components)


def _check_tasks(records: list[tuple[str, Task]], issues: _IssueLog) -> None:
    projects: dict[str, dict[str, str]] = {}
    for path, task in records:
        paths = projects.setdefault(task.project, {})
        if task.id in paths:
            issues.append(Issue(path, "id", f"duplicate task id {bounded_repr(task.id)}"))
        else:
            paths[task.id] = path

    graphs: dict[str, dict[str, list[str]]] = {
        project: {task_id: [] for task_id in paths} for project, paths in projects.items()
    }
    for path, task in records:
        graph = graphs[task.project]
        for target in task.depends_on:
            if target not in graph:
                issues.append(Issue(path, "depends_on", f"unknown task id {bounded_repr(target)}"))
            elif path == projects[task.project][task.id]:
                graph[task.id].append(target)
    for project, graph in graphs.items():
        for component in _cyclic_components(graph):
            members = bounded_repr(", ".join(component))
            path = projects[project][component[0]]
            issues.append(Issue(path, "depends_on", f"dependency cycle among task ids {members}"))


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


def load_workspace(root: Path, *, validate_all: bool = False) -> Workspace:
    issues = _IssueLog(None) if validate_all else _IssueLog()
    try:
        with _directory(root) as fd:
            research = _load_dir(root, fd, "research", load_research, issues)
            decisions = _load_dir(root, fd, "decisions", load_decision, issues)
            features = _load_dir(root, fd, "features", _load_feature, issues)
            tasks = _load_dir(root, fd, "tasks", _load_task, issues)
            milestones = _load_dir(root, fd, "milestones", load_scoped_milestone, issues)
            if validate_all:
                _load_dir(root, fd, "visions", parse_vision, issues)
    except (OSError, ValueError, RuntimeError) as exc:
        detail = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
        if isinstance(exc, OSError) and exc.errno == errno.ENOTDIR:
            detail = "not a directory or a symlink is present"
        raise WorkspaceError(root, "workspace", detail) from None
    ws = Workspace(
        tuple(research),
        tuple(decisions),
        tuple(features),
        (),
        tasks=tuple(t for _, t in tasks),
        milestones=tuple(milestones),
    )
    _cross_validate(ws, issues)
    _check_tasks(tasks, issues)
    known_milestones = {(project, milestone.id) for project, milestone in milestones}
    for path, task in tasks:
        if task.milestone and (task.project, task.milestone) not in known_milestones:
            issues.append(
                Issue(path, "milestone", f"unknown milestone id {bounded_repr(task.milestone)}")
            )
    warnings = tuple(w for feature in ws.features for w in link_warnings(ws, feature))
    return replace(
        ws, issues=tuple(issues.issues), warnings=warnings, omitted_issues=issues.omitted
    )
