"""Load an intent workspace (``research/``, ``decisions/``, ``features/<project>/``).

Every file and cross-file problem is collected as an ``Issue``; loading never stops at the
first error and unresolved references are reported as ``missing`` rather than raised.
"""

from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Issue:
    """A problem in a file (``path`` is workspace-relative) or in a record (``path`` is its ref)."""

    path: str
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.path}: field '{self.field}'" if self.field else self.path
        return f"{where}: {self.message}"


@dataclass(frozen=True)
class Workspace:
    research: tuple[ResearchArtifact, ...]
    decisions: tuple[Decision, ...]
    features: tuple[Feature, ...]
    issues: tuple[Issue, ...]
    warnings: tuple[Issue, ...] = ()

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


def _check_path(root: Path, path: Path, fd: int) -> int:
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError("symlink is not allowed")
    if not path.resolve().is_relative_to(root):
        raise ValueError("resolved path is outside the workspace")
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


def _entries(root: Path, base: Path, fd: int, issues: list[Issue]) -> Iterator[tuple[Path, int]]:
    try:
        names = sorted(os.listdir(fd))
    except OSError as exc:
        issues.append(_issue(root, base, exc))
        return
    for name in names:
        path = base / name
        try:
            mode = _check_path(root, path, fd)
        except (OSError, ValueError, RuntimeError) as exc:
            issues.append(_issue(root, path, exc))
            continue
        yield path, mode


def _walk_markdown(
    root: Path, base: Path, fd: int, issues: list[Issue], *, descend: bool
) -> Iterator[tuple[Path, int]]:
    stack = [(_entries(root, base, fd, issues), fd, ExitStack())]
    try:
        while stack:
            entries, folder_fd, scope = stack[-1]
            item = next(entries, None)
            if item is None:
                stack.pop()
                scope.close()
                continue
            path, mode = item
            if descend and stat.S_ISDIR(mode):
                child_scope = ExitStack()
                try:
                    child_fd = child_scope.enter_context(_directory(path, folder_fd))
                except OSError as exc:
                    issues.append(_issue(root, path, exc))
                    continue
                stack.append((_entries(root, path, child_fd, issues), child_fd, child_scope))
            elif path.name.endswith(".md"):
                if stat.S_ISREG(mode):
                    yield path, folder_fd
                else:
                    issues.append(
                        Issue(path.relative_to(root).as_posix(), None, "expected a regular file")
                    )
    finally:
        for _, _, scope in reversed(stack):
            scope.close()


def _load_dir[T](
    root: Path, root_fd: int, sub: str, loader: Callable[..., T], issues: list[Issue]
) -> list[T]:
    base = root / sub
    try:
        mode = _check_path(root, base, root_fd)
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RuntimeError) as exc:
        issues.append(_issue(root, base, exc))
        return []
    if not stat.S_ISDIR(mode):
        issues.append(Issue(sub, None, "expected a directory"))
        return []
    out: list[T] = []
    try:
        with _directory(base, root_fd) as fd:
            for path, folder_fd in _walk_markdown(
                root, base, fd, issues, descend=sub == "features"
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


def _duplicates(records: list[Ref], issues: list[Issue]) -> None:
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


def _check_decision(ws: Workspace, d: Decision) -> list[Issue]:
    owner, out = Ref("decision", d.id), []
    for ref in d.evidence:
        if not _has_research_ref(ws, ref):
            out.append(_missing(owner, "evidence", ref))
    out += [
        _missing(owner, "features", ref) for ref in d.features if not ws.get_feature_by_ref(ref)
    ]
    return out


def _check_feature(ws: Workspace, f: Feature) -> list[Issue]:
    owner = feature_ref(f)
    out = [_missing(owner, "research", r) for r in f.research if not _has_research_ref(ws, r)]
    out += [_missing(owner, "decisions", d) for d in f.decisions if not ws.get_decision(d.id)]
    if f.status == "planned" and not any(d.status == "approved" for d in linked_decisions(ws, f)):
        out.append(
            Issue(
                str(owner),
                "status",
                "status 'planned' requires a linked Decision with status approved",
            )
        )
    return out


def _cross_validate(ws: Workspace) -> list[Issue]:
    issues: list[Issue] = []
    _duplicates([Ref("research", r.id) for r in ws.research], issues)
    _duplicates([Ref("decision", d.id) for d in ws.decisions], issues)
    _duplicates([feature_ref(f) for f in ws.features], issues)
    for d in ws.decisions:
        issues += _check_decision(ws, d)
    for f in ws.features:
        issues += _check_feature(ws, f)
    return issues


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
    issues: list[Issue] = []
    try:
        mode = root.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("symlink is not allowed")
        if not stat.S_ISDIR(mode):
            raise ValueError("is not a directory")
        with _directory(root) as fd:
            resolved = root.resolve()
            research = _load_dir(resolved, fd, "research", load_research, issues)
            decisions = _load_dir(resolved, fd, "decisions", load_decision, issues)
            features = _load_dir(resolved, fd, "features", _load_feature, issues)
    except (OSError, ValueError, RuntimeError) as exc:
        detail = (exc.strerror or str(exc)) if isinstance(exc, OSError) else str(exc)
        raise WorkspaceError(f"workspace {bounded_repr(str(root))}: {detail}") from exc
    ws = Workspace(tuple(research), tuple(decisions), tuple(features), ())
    warnings = tuple(w for feature in ws.features for w in link_warnings(ws, feature))
    return Workspace(
        ws.research, ws.decisions, ws.features, tuple(issues + _cross_validate(ws)), warnings
    )
