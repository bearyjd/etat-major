"""Propose component rows using recorded Gradle and Trail module evidence."""

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from etat_major.component_paths import component_path, literal_prefix
from etat_major.components import (
    MAX_COMPONENT_ID_LENGTH,
    MAX_COMPONENT_PATH_LENGTH,
    MAX_COMPONENTS,
    MAX_PATHS,
    MAX_PROJECT_ID_LENGTH,
    ComponentModel,
    load_components,
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

    def dump(self) -> str:
        data = {"id": self.id, "label": self.label, "kind": _KIND, "paths": list(self.paths)}
        if self.parent is not None:
            data["parent"] = self.parent
        return _COMMENT + yaml.safe_dump([data], sort_keys=False)


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


def _propose(
    modules: list[Module], existing: ComponentModel | None, destination: Path
) -> list[_Proposal]:
    prior = existing.components if existing else ()
    prior_by_id = {component.id: component for component in prior}
    occupied = set(prior_by_id)
    path_owners = {
        path.removesuffix("/**"): component.id for component in prior for path in component.paths
    }
    parents = {component.id: component.id for component in prior if not component.paths}
    parents.update(path_owners)
    proposals: list[_Proposal] = []
    for module in sorted(modules, key=lambda item: (item.directory, item.id)):
        path = module.directory or _ROOT_GLOB
        if path in path_owners:
            continue
        if len(path) > MAX_COMPONENT_PATH_LENGTH:
            raise TaskFileError(
                destination,
                "paths",
                f"module directory exceeds {MAX_COMPONENT_PATH_LENGTH} characters",
            )
        is_root = path == _ROOT_GLOB
        base = "root" if is_root else _path_id(path)
        authored = prior_by_id.get(base)
        if authored and any(literal_prefix(item).startswith(path + "/") for item in authored.paths):
            continue
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
        path_owners[path] = component_id
        parents.setdefault(path, component_id)
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
