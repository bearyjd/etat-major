"""Propose component rows using recorded Gradle and Trail module evidence."""

import os
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from etat_major.component_paths import component_path, literal_prefix, matches
from etat_major.components import (
    MAX_COMPONENT_ID_LENGTH,
    MAX_COMPONENT_PATH_LENGTH,
    MAX_COMPONENTS,
    MAX_PATHS,
    MAX_PROJECT_ID_LENGTH,
    ComponentModel,
    load_components,
    validate_component_document,
)
from etat_major.gradle import Module, load_dependencies
from etat_major.localfiles import open_directory, write_new_text
from etat_major.refs import PROJECT_ID
from etat_major.taskfile import TaskFileError
from etat_major.trail import load_wiring
from etat_major.workspace import Issue

_KIND = "inferred_from_gradle"
_ROOT_GLOB = "**"
_COMMENT = "# Proposal for human review.\n"
_ID_SEPARATOR = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class SeedResult:
    output: str
    project: str
    components: tuple[str, ...]
    issues: tuple[Issue, ...]


@dataclass(frozen=True)
class _Proposal:
    id: str
    label: str
    paths: tuple[str, ...]
    parent: str | None

    def record(self) -> dict:
        data = {"id": self.id, "label": self.label, "kind": _KIND, "paths": list(self.paths)}
        if self.parent is not None:
            data["parent"] = self.parent
        return data

    def dump(self) -> str:
        return _COMMENT + yaml.safe_dump([self.record()], sort_keys=False)


def _trail_scope(supplied: str, trail: Path, index: int) -> None:
    if not supplied:
        return
    field = f"meta.scopes[{index}].prefix"
    try:
        component_path(supplied)
    except ValueError:
        raise TaskFileError(trail, field, "expected a safe repository-relative path") from None
    if len(supplied) > MAX_COMPONENT_PATH_LENGTH or any(char in supplied for char in "*?["):
        raise TaskFileError(
            trail,
            field,
            f"expected a literal module directory up to {MAX_COMPONENT_PATH_LENGTH} characters",
        )


def _module_evidence(root: Path, trail: Path | None) -> tuple[list[Module], list[Issue]]:
    gradle = load_dependencies(root)
    modules = list(gradle.modules)
    issues = [
        replace(issue, blocking=False) if issue.field == "dependencies" else issue
        for issue in gradle.issues
    ]
    _require_usable(issues)
    if trail is None:
        return modules, issues
    directories = {module.directory for module in modules}
    by_id = {module.id: module.directory for module in modules}
    for index, scope in enumerate(load_wiring(trail).module_scopes):
        _trail_scope(scope, trail, index)
        if scope in directories:
            continue
        module_id = ":" + scope.replace("/", ":")
        if module_id in by_id:
            issues.append(
                Issue(
                    trail.name,
                    "meta.scopes",
                    f"scope {scope} disagrees with Gradle directory {by_id[module_id]}",
                    severity="warning",
                    blocking=False,
                )
            )
        else:
            modules.append(Module(module_id, scope))
            directories.add(scope)
    return modules, issues


def _require_usable(issues: tuple[Issue, ...] | list[Issue]) -> None:
    for issue in issues:
        if issue.blocking:
            raise TaskFileError(Path(issue.path), issue.field, issue.message)


def _existing_model(
    proposal_for: Path | None, project: str, issues: list[Issue]
) -> ComponentModel | None:
    if proposal_for is None:
        return None
    model, diagnostics = load_components(proposal_for)
    _require_usable(diagnostics)
    if model is None or model.project != project:
        raise TaskFileError(proposal_for, "project", "expected the selected project")
    issues.extend(diagnostics)
    return model


def _path_id(path: str) -> str:
    return ".".join(
        _ID_SEPARATOR.sub("-", part.lower()).strip("-_") or "module" for part in path.split("/")
    )


def _allocate(base: str, occupied: set[str]) -> str:
    base = base[:MAX_COMPONENT_ID_LENGTH].rstrip(".")
    component_id = base
    number = 2
    while component_id in occupied:
        suffix = f"-{number}"
        stem = base[: MAX_COMPONENT_ID_LENGTH - len(suffix)].rstrip(".")
        component_id = stem + suffix
        number += 1
    occupied.add(component_id)
    return component_id


def _scoped_parents(existing: ComponentModel | None) -> dict[str, str]:
    if existing is None:
        return {}
    pathless = {row.id for row in existing.components if not row.paths}
    heads_by_parent: dict[str, set[str]] = defaultdict(set)
    for row in existing.components:
        if row.parent not in pathless:
            continue
        for path in row.paths:
            head, separator, _ = literal_prefix(path).partition("/")
            if separator:
                heads_by_parent[row.parent].add(head)
    parents_by_head: dict[str, list[str]] = defaultdict(list)
    for parent, heads in heads_by_parent.items():
        if len(heads) == 1:
            parents_by_head[next(iter(heads))].append(parent)
    return {head: parents[0] for head, parents in parents_by_head.items() if len(parents) == 1}


def _module_scope(pattern: str, directories: set[str]) -> str:
    prefix = literal_prefix(pattern)
    scope = prefix.rstrip("/")
    if prefix != pattern and not prefix.endswith("/"):
        scope = scope.rpartition("/")[0]
    while scope and scope not in directories:
        scope = scope.rpartition("/")[0]
    return scope


def _missing_paths(modules: list[Module], authored_paths: tuple[str, ...], path: Path) -> list[str]:
    directories = set()
    for module in modules:
        if any(char in module.directory for char in "*?["):
            raise TaskFileError(path, "paths", "expected a literal module directory")
        directories.add(module.directory or _ROOT_GLOB)
    scoped = {pattern for pattern in authored_paths if literal_prefix(pattern)}
    claimed = {_module_scope(pattern, directories) for pattern in scoped}
    missing = []
    for directory in sorted(directories):
        try:
            component_path(directory)
        except ValueError as exc:
            raise TaskFileError(path, "paths", str(exc)) from None
        if len(directory) > MAX_COMPONENT_PATH_LENGTH:
            raise TaskFileError(
                path, "paths", f"module directory exceeds {MAX_COMPONENT_PATH_LENGTH} characters"
            )
        if directory == _ROOT_GLOB:
            owned = directory in authored_paths
        else:
            owned = directory in claimed or any(matches(pattern, directory) for pattern in scoped)
        if not owned:
            missing.append(directory)
    return missing


def _authored_parents(existing: ComponentModel | None, missing: list[str]) -> dict[str, str]:
    if existing is None:
        return {}
    parents = _scoped_parents(existing)
    for row in existing.components:
        if _ROOT_GLOB in row.paths:
            parents.setdefault(_ROOT_GLOB, row.id)
    for head in {path.partition("/")[0] for path in missing if "/" in path}:
        owner = existing.owner_of(head).component
        if owner and any(literal_prefix(path) and matches(path, head) for path in owner.paths):
            parents[head] = owner.id
    return parents


def _propose(
    modules: list[Module], existing: ComponentModel | None, destination: Path
) -> list[_Proposal]:
    prior = existing.components if existing else ()
    occupied = {component.id for component in prior}
    authored_paths = tuple(path for component in prior for path in component.paths)
    missing = _missing_paths(modules, authored_paths, destination)
    parents = _authored_parents(existing, missing)
    proposals: list[_Proposal] = []
    for path in missing:
        is_root = path == _ROOT_GLOB
        base = "root" if is_root else _path_id(path)
        parent = parents.get(_ROOT_GLOB)
        head, sep, _ = path.partition("/")
        if sep:
            if head not in parents:
                group_id = _allocate(_path_id(head), occupied)
                proposals.append(_Proposal(group_id, head, (), parent))
                parents[head] = group_id
            parent = parents[head]
        component_id = _allocate(base, occupied)
        proposals.append(_Proposal(component_id, "Root" if is_root else path, (path,), parent))
        parents[path] = component_id
        if len(occupied) > MAX_COMPONENTS:
            raise TaskFileError(destination, "components", f"limit is {MAX_COMPONENTS} components")
    if sum(len(row.paths) for row in [*prior, *proposals]) > MAX_PATHS:
        raise TaskFileError(destination, "paths", f"limit is {MAX_PATHS} component paths")
    return proposals


def _yaml_text(project: str, proposals: list[_Proposal]) -> str:
    fields = {"version": 1, "project": project}
    if not proposals:
        fields["components"] = []
        return yaml.safe_dump(fields, sort_keys=False)
    return (
        yaml.safe_dump(fields, sort_keys=False)
        + "components:\n"
        + "".join(row.dump() for row in proposals)
    )


def _validate_proposal(
    destination: Path, project: str, existing: ComponentModel | None, proposals: list[_Proposal]
) -> None:
    rows = [
        component.model_dump(mode="json", exclude_none=True)
        for component in (existing.components if existing else ())
    ]
    rows.extend(row.record() for row in proposals)
    _, issues = validate_component_document(
        {"version": 1, "project": project, "components": rows}, destination
    )
    _require_usable(issues)


def _publish_proposal(
    destination: Path,
    field: str,
    root: Path,
    project: str,
    trail: Path | None,
    original: Path | None,
) -> SeedResult:
    try:
        with open_directory(destination.parent) as fd:
            try:
                os.stat(destination.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError
            modules, issues = _module_evidence(root, trail)
            existing = _existing_model(original, project, issues)
            proposals = _propose(modules, existing, destination)
            _validate_proposal(destination, project, existing, proposals)
            write_new_text(destination, _yaml_text(project, proposals), dir_fd=fd)
    except FileExistsError:
        raise TaskFileError(destination, field, "proposal output already exists") from None
    except TaskFileError:
        raise
    except (OSError, ValueError):
        raise TaskFileError(
            destination, field, "cannot create a symlink-free proposal file"
        ) from None
    return SeedResult(destination.name, project, tuple(row.id for row in proposals), tuple(issues))


def seed_components(
    root: Path,
    project: str,
    *,
    trail: Path | None = None,
    out: Path | None = None,
    proposal_for: Path | None = None,
) -> SeedResult:
    """Write a new component draft or a delta alongside an existing component model."""
    if (out is None) == (proposal_for is None):
        raise TaskFileError(Path("components"), "out", "specify either out or proposal_for")
    if len(project) > MAX_PROJECT_ID_LENGTH or not re.fullmatch(PROJECT_ID, project):
        raise TaskFileError(Path("components"), "project", "expected a project id")
    if proposal_for is not None:
        if not proposal_for.name:
            raise TaskFileError(proposal_for, "proposal_for", "expected a component model filename")
        destination = proposal_for.with_name(f"{proposal_for.name}.proposed")
        return _publish_proposal(destination, "proposal_for", root, project, trail, proposal_for)
    return _publish_proposal(out, "out", root, project, trail, None)
