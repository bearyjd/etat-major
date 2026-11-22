"""Read Git-backed component declarations and derive repository path ownership."""

import re
import stat
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from etat_major.component_paths import (
    OverlapLimit,
    component_file_path,
    component_path,
    literal_prefix,
    matches,
    overlap_checker,
)
from etat_major.localfiles import entry_mode, open_directory, read_text
from etat_major.refs import COMPONENT_ID, PROJECT_ID
from etat_major.taskfile import (
    CalendarDate,
    TaskFileError,
    first_error,
    parse_yaml_mapping,
)
from etat_major.text_safety import public_text
from etat_major.workspace import Issue, _cyclic_components, _entries, _IssueLog

MAX_COMPONENTS = 500
MAX_PATHS = 1000
MAX_PROJECT_ID_LENGTH = 128
MAX_COMPONENT_ID_LENGTH = 256
MAX_COMPONENT_PATH_LENGTH = 256
_MAX_DEPTH = 32
_MAX_YAML_EVENTS = 20_000

ProjectId = Annotated[
    StrictStr, Field(pattern=rf"^{PROJECT_ID}$", max_length=MAX_PROJECT_ID_LENGTH)
]
ComponentId = Annotated[
    StrictStr, Field(pattern=rf"^{COMPONENT_ID}$", max_length=MAX_COMPONENT_ID_LENGTH)
]
ComponentPath = Annotated[
    StrictStr, Field(max_length=MAX_COMPONENT_PATH_LENGTH), AfterValidator(component_path)
]
NonEmptyText = Annotated[StrictStr, Field(min_length=1)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Summary(_Record):
    text: NonEmptyText
    provenance: Literal["human", "ai-generated", "inferred", "verified"]
    reviewed_by: NonEmptyText | None = None
    reviewed_on: CalendarDate | None = None

    @field_validator("reviewed_by")
    @classmethod
    def _reviewer(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("expected a reviewer name")
        return value

    @field_validator("reviewed_on", mode="before")
    @classmethod
    def _review_pair(cls, value: object, info: ValidationInfo) -> object:
        if value is None or info.data.get("reviewed_by") is None:
            raise ValueError("reviewed_by and reviewed_on must appear together")
        return value

    @model_validator(mode="after")
    def _review_date(self) -> "Summary":
        if self.reviewed_by is not None and self.reviewed_on is None:
            raise ValueError("reviewed_by and reviewed_on must appear together")
        return self


class Component(_Record):
    id: ComponentId
    label: NonEmptyText
    parent: ComponentId | None = None
    kind: NonEmptyText
    paths: Annotated[tuple[ComponentPath, ...], Field(max_length=MAX_PATHS)]
    owner: NonEmptyText | None = None
    summary: Summary | None = None


@dataclass(frozen=True)
class Ownership:
    component: Component | None = None
    ties: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    owned: tuple[str, ...]
    unowned: tuple[str, ...]
    percentage: float
    ties: tuple[tuple[str, tuple[str, ...]], ...]


class ComponentModel(_Record):
    version: Annotated[StrictInt, Field(ge=1, le=1)]
    project: ProjectId
    components: Annotated[tuple[Component, ...], Field(max_length=MAX_COMPONENTS)]

    def get(self, ident: str) -> Component | None:
        return next((component for component in self.components if component.id == ident), None)

    def children_of(self, ident: str) -> tuple[Component, ...]:
        return tuple(
            sorted(
                (component for component in self.components if component.parent == ident),
                key=lambda component: component.id,
            )
        )

    def ancestors_of(self, ident: str) -> tuple[Component, ...]:
        by_id = {component.id: component for component in self.components}
        chain = []
        seen = {ident}
        while (component := by_id.get(ident)) and component.parent not in seen:
            parent = by_id.get(component.parent)
            if parent is None:
                break
            chain.append(parent)
            ident = parent.id
            seen.add(ident)
        return tuple(chain)

    def owner_of(self, path: str) -> Ownership:
        component_file_path(path)
        return _owner(path, _patterns(self.components))

    def coverage(self, file_paths: Iterable[str]) -> Coverage:
        patterns = _patterns(self.components)
        owned, unowned, ties = [], [], []
        for path in sorted(set(file_paths)):
            component_file_path(path)
            result = _owner(path, patterns)
            (owned if result.component else unowned).append(path)
            if result.ties:
                ties.append((path, result.ties))
        count = len(owned) + len(unowned)
        return Coverage(
            tuple(owned), tuple(unowned), 100 * len(owned) / count if count else 0.0, tuple(ties)
        )


def _patterns(components: tuple[Component, ...]) -> list[tuple[int, str, Component]]:
    return sorted(
        ((len(literal_prefix(path)), path, row) for row in components for path in row.paths),
        key=lambda item: (-item[0], item[2].id, item[1]),
    )


def _owner(path: str, patterns: list[tuple[int, str, Component]]) -> Ownership:
    best = -1
    winners = {}
    for score, pattern, component in patterns:
        if score < best:
            break
        if matches(pattern, path):
            best = score
            winners[component.id] = component
    if len(winners) == 1:
        return Ownership(next(iter(winners.values())))
    return Ownership(ties=tuple(winners))


def _bounded_yaml(text: str, path: Path) -> dict:
    depth = 0
    try:
        for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), 1):
            if count > _MAX_YAML_EVENTS:
                raise TaskFileError(path, "components", "YAML exceeds the 20000-event limit")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > _MAX_DEPTH:
                    raise TaskFileError(path, "components", "YAML exceeds the 32-level depth limit")
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            elif isinstance(event, yaml.AliasEvent):
                raise TaskFileError(path, "components", "YAML aliases are not allowed")
    except (yaml.YAMLError, RecursionError):
        raise TaskFileError(path, "components", "invalid component YAML") from None
    return parse_yaml_mapping(text, path, field="components")


def _validation_issues(path: Path, error: ValidationError) -> list[Issue]:
    issues = []
    for item in error.errors(include_input=False, include_url=False):
        issue = first_error(path, item)
        issues.append(Issue(path.name, issue.field_name, public_text(issue.message)))
    return issues


def _valid_rows(raw: object) -> list[tuple[int, Component]]:
    if not isinstance(raw, list) or len(raw) > MAX_COMPONENTS:
        return []
    rows = []
    for index, entry in enumerate(raw):
        try:
            rows.append((index, Component.model_validate(entry)))
        except ValidationError:
            continue
    return rows


def _relationship_rows(raw: object) -> list[tuple[int, str, str | None, bool]]:
    if not isinstance(raw, list) or len(raw) > MAX_COMPONENTS:
        return []
    rows = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            continue
        ident, parent = entry.get("id"), entry.get("parent")
        if not _is_component_id(ident):
            continue
        rows.append(
            (index, ident, parent if _is_component_id(parent) else None, entry.get("paths") == [])
        )
    return rows


def _is_component_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_COMPONENT_ID_LENGTH
        and bool(re.fullmatch(COMPONENT_ID, value))
    )


def _relationships(raw: object, path: Path) -> list[Issue]:
    rows = _relationship_rows(raw)
    issues = []
    graph = {ident: [] for _, ident, _, _ in rows}
    children = {parent for _, _, parent, _ in rows}
    seen = set()
    for index, ident, parent, empty in rows:
        field = f"components.{index}"
        duplicate = ident in seen
        if duplicate:
            issues.append(Issue(path.name, f"{field}.id", f"duplicate component id {ident}"))
        seen.add(ident)
        if parent is not None:
            if parent not in graph:
                issues.append(Issue(path.name, f"{field}.parent", f"unknown parent {parent}"))
            elif not duplicate:
                graph[ident].append(parent)
        if empty and ident not in children:
            issues.append(
                Issue(path.name, f"{field}.paths", "a component without paths needs children")
            )
    cycles = {ident: cycle for cycle in _cyclic_components(graph) for ident in cycle}
    for index, ident, _, _ in rows:
        if ident in cycles:
            cycle = ", ".join(cycles[ident])
            issues.append(Issue(path.name, f"components.{index}.parent", f"parent cycle: {cycle}"))
    return issues


def _overlap_issues(rows: list[tuple[int, Component]], path: Path) -> list[Issue]:
    siblings = defaultdict(list)
    overlaps = overlap_checker()
    for index, row in rows:
        siblings[row.parent].append((index, row))
    issues = []
    for group in siblings.values():
        for (index, a), (_, b) in combinations(group, 2):
            if a.id != b.id and any(overlaps(x, y) for x in a.paths for y in b.paths):
                issues.append(
                    Issue(
                        path.name,
                        f"components.{index}.paths",
                        f"sibling paths overlap: {a.id} and {b.id}",
                        "warning",
                        False,
                    )
                )
    return issues


def load_components(
    path: Path, *, dir_fd: int | None = None
) -> tuple[ComponentModel | None, tuple[Issue, ...]]:
    """Read one file. Invalid documents return diagnostics and no ownership model."""
    try:
        if dir_fd is None:
            with open_directory(path.parent) as parent:
                return load_components(path, dir_fd=parent)
        raw = _bounded_yaml(read_text(path, 1, dir_fd=dir_fd), path)
    except TaskFileError as exc:
        return None, (Issue(path.name, exc.field_name, public_text(exc.message)),)
    except (OSError, ValueError) as exc:
        return None, (Issue(path.name, "file", _io_message(exc)),)

    issues = []
    try:
        model = ComponentModel.model_validate(raw)
        rows = list(enumerate(model.components))
    except ValidationError as exc:
        model = None
        issues.extend(_validation_issues(path, exc))
        rows = _valid_rows(raw.get("components"))
    issues.extend(_relationships(raw.get("components"), path))
    if sum(len(row.paths) for _, row in rows) > MAX_PATHS:
        issues.append(Issue(path.name, "components", f"components exceed {MAX_PATHS} paths"))
    else:
        try:
            issues.extend(_overlap_issues(rows, path))
        except OverlapLimit as exc:
            issues.append(Issue(path.name, "components", str(exc)))
    if any(issue.severity == "error" for issue in issues):
        model = None
    return model, tuple(issues)


def _io_message(error: OSError | ValueError) -> str:
    return public_text(
        (error.strerror or "I/O error") if isinstance(error, OSError) else str(error)
    )


def _read_directory(
    directory: Path, fd: int
) -> tuple[dict[str, ComponentModel], tuple[Issue, ...]]:
    models = {}
    issues = _IssueLog(limit=None)
    for path, mode in _entries(directory, directory, fd, issues):
        if path.suffix != ".yaml":
            continue
        if not stat.S_ISREG(mode):
            issues.append(Issue(path.name, "file", "expected a regular file"))
            continue
        model, diagnostics = load_components(path, dir_fd=fd)
        for issue in diagnostics:
            issues.append(issue)
        if model is not None and model.project != path.stem:
            issues.append(Issue(path.name, "project", "project must match the YAML filename"))
        elif model is not None:
            models[model.project] = model
    return models, tuple(replace(i, field=i.field or "file") for i in issues.issues)


def load_component_directory(
    directory: Path,
) -> tuple[dict[str, ComponentModel], tuple[Issue, ...]]:
    with open_directory(directory) as fd:
        return _read_directory(directory, fd)


def _workspace_directory(root_fd: int) -> tuple[dict[str, ComponentModel], tuple[Issue, ...]]:
    directory = Path("components")
    try:
        mode = entry_mode(directory, root_fd)
        if not stat.S_ISDIR(mode):
            return {}, (Issue("components", "file", "expected a directory"),)
        with open_directory(directory, root_fd) as fd:
            models, issues = _read_directory(directory, fd)
    except FileNotFoundError:
        return {}, ()
    except (OSError, ValueError) as exc:
        return {}, (Issue("components", "file", _io_message(exc)),)
    return models, tuple(
        replace(i, path="components" if i.path == "." else f"components/{i.path}") for i in issues
    )


def load_component_workspace(root: Path) -> tuple[dict[str, ComponentModel], tuple[Issue, ...]]:
    try:
        with open_directory(root) as root_fd:
            return _workspace_directory(root_fd)
    except (OSError, ValueError) as exc:
        raise TaskFileError(root, "workspace", _io_message(exc)) from None
