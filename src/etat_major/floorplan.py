"""Read-only readers for Floorplan code maps and blueprints.

The trace reader keeps component IDs and file paths. The architecture reader
keeps structured graph fields and discards roots, remotes and free-form prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, overload

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    computed_field,
    field_validator,
)

from etat_major.localfiles import open_directory, read_text, read_text_kib
from etat_major.refs import Ref, RefError, parse_ref
from etat_major.taskfile import TaskFileError, check_recorded_array, first_error
from etat_major.text_safety import bounded_repr

SUPPORTED_SCHEMA = "floorplan/graph@1"
FLOORPLAN_COMMIT = "94f81b463b7617e06d873ac71323ce71644c8399"
PLAN_SCHEMA = "floorplan/plan@1"
_LIMIT_MIB = 64
_SCHEMA_LABEL = re.compile(r"(?:floorplan/)?[a-zA-Z0-9_@.-]*")


class FloorplanError(TaskFileError):
    """A Floorplan artifact is unreadable or invalid."""


@dataclass(frozen=True)
class FloorplanPlan:
    file_paths: frozenset[str]


class _PlanObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _PlanFile(_PlanObject):
    path: StrictStr
    name: StrictStr
    description: StrictStr

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        if not _is_relative_path(value):
            raise ValueError("expected a repository-relative Floorplan file path")
        return value


class _PlanDocument(_PlanObject):
    source: StrictStr = ""
    stack: tuple[StrictStr, ...] = ()
    assumptions: tuple[StrictStr, ...] = ()
    questions: tuple[_PlanObject, ...] = ()
    files: tuple[_PlanFile, ...]
    endpoints: tuple[_PlanObject, ...] = ()


@dataclass(frozen=True)
class FloorplanIndex:
    node_ids: frozenset[str]
    file_paths: frozenset[str]

    def has_node(self, node_id: str) -> bool:
        return node_id in self.node_ids

    def has_file(self, path: str) -> bool:
        return path in self.file_paths

    def resolve(self, ref: Ref) -> bool:
        """Whether an ``fp:n:`` or ``fp:f:`` reference exists in this graph."""
        if ref.kind == "fp:n":
            return self.has_node(ref.id)
        if ref.kind == "fp:f":
            return self.has_file(ref.id)
        raise ValueError(
            f"only fp: references resolve against a Floorplan graph, got {bounded_repr(str(ref))}"
        )


def _is_relative_path(value: str) -> bool:
    parts = value.split("/")
    return (
        not {"", ".", ".."}.intersection(parts)
        and not value.startswith("~")
        and ":" not in parts[0]
        and "\\" not in value
        and "\0" not in value
    )


def _collect(path: Path, data: dict[str, Any], key: str, field: str) -> frozenset[str]:
    items = data.get(key)
    if not isinstance(items, list):
        raise FloorplanError(path, key, "must be a list")
    values: set[str] = set()
    for i, item in enumerate(items):
        value = item.get(field) if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise FloorplanError(path, f"{key}[{i}].{field}", "needs a non-empty string")
        if key == "files" and not _is_relative_path(value):
            raise FloorplanError(path, f"{key}[{i}].{field}", "must be repository-relative")
        values.add(value)
    return frozenset(values)


@overload
def load_graph(path: Path, *, architecture: Literal[False] = False) -> FloorplanIndex: ...


@overload
def load_graph(path: Path, *, architecture: Literal[True]) -> ArchitectureDocument: ...


def load_graph(path: Path, *, architecture: bool = False) -> FloorplanIndex | ArchitectureDocument:
    """Read a recorded graph, with structured nodes and links when requested."""
    if architecture:
        return load_architecture(path)
    data = _graph_document(path)
    return FloorplanIndex(_collect(path, data, "nodes", "id"), _collect(path, data, "files", "p"))


def _graph_document(path: Path, *, limit_kib: int | None = None) -> dict[str, Any]:
    data = _read_json(path, limit_kib=limit_kib)
    if "schema" not in data:
        raise FloorplanError(
            path, "schema", f"missing schema; only {SUPPORTED_SCHEMA!r} is supported"
        )
    schema = data["schema"]
    if schema != SUPPORTED_SCHEMA:
        detail = " " + bounded_repr(schema)
        if isinstance(schema, str) and not _SCHEMA_LABEL.fullmatch(schema):
            detail = ""
        raise FloorplanError(
            path, "schema", f"unsupported schema{detail}; only {SUPPORTED_SCHEMA!r} is supported"
        )
    for field in ("nodes", "files", "routes", "links"):
        check_recorded_array(path, field, data.get(field), error=FloorplanError)
    return data


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _read_json(path: Path, *, limit_kib: int | None = None) -> dict[str, Any]:
    try:
        with open_directory(path.parent) as fd:
            text = (
                read_text(path, _LIMIT_MIB, dir_fd=fd)
                if limit_kib is None
                else read_text_kib(path, limit_kib, dir_fd=fd)
            )
    except (OSError, UnicodeError):
        raise FloorplanError(path, "JSON", "cannot read file as UTF-8") from None
    except ValueError as exc:
        raise FloorplanError(path, "JSON", f"cannot read file: {exc}") from None
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        raise FloorplanError(path, "JSON", "invalid JSON") from None
    if not isinstance(data, dict):
        raise FloorplanError(path, "JSON", "expected an object")
    return data


def load_plan(path: Path) -> FloorplanPlan:
    """Validate a Floorplan blueprint and keep only its planned file paths."""
    data = _read_json(path)
    for key in ("$schema", "schema"):
        if key in data and data[key] != PLAN_SCHEMA:
            raise FloorplanError(path, key, f"expected {PLAN_SCHEMA}")
    for field in ("files", "stack", "assumptions", "questions", "endpoints"):
        check_recorded_array(path, field, data.get(field), error=FloorplanError)
    try:
        plan = _PlanDocument.model_validate(data)
    except ValidationError as exc:
        error = first_error(path, exc)
        raise FloorplanError(path, error.field, error.message) from None
    return FloorplanPlan(frozenset(file.path for file in plan.files))


def _code_path(value: str) -> str:
    if ":" in value:
        raise ValueError("expected a repository-relative file path")
    try:
        parse_ref(f"fp:f:{value}")
    except RefError:
        raise ValueError("expected a repository-relative file path") from None
    return value


def _endpoint(value: str) -> str:
    prefix, _, identifier = value.partition(":")
    if prefix == "f":
        _code_path(identifier)
    elif prefix not in {"n", "r"} or not re.fullmatch(r"[\w.@-]+", identifier):
        raise ValueError("expected a Floorplan file, component or route ID")
    return value


type CodePath = Annotated[StrictStr, AfterValidator(_code_path)]
type WireLabel = Annotated[StrictStr, Field(pattern=r"^[\w.@-]+$")]


class _ArchitectureItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    layer: Literal["architecture"] = "architecture"


class Component(_ArchitectureItem):
    id: WireLabel
    kind: WireLabel | None = None

    @computed_field
    @property
    def provenance(self) -> Literal["inferred"]:
        return "inferred"


class ArchitectureFile(_ArchitectureItem):
    path: CodePath = Field(alias="p")
    component_id: WireLabel | None = Field(default=None, alias="n")
    language: WireLabel | None = Field(default=None, alias="l")
    lines: Annotated[int, Field(strict=True, ge=0)] | None = Field(default=None, alias="loc")

    @computed_field
    @property
    def provenance(self) -> Literal["verified"]:
        return "verified"


class ArchitectureLink(_ArchitectureItem):
    source: Annotated[StrictStr, AfterValidator(_endpoint)] = Field(alias="a")
    target: Annotated[StrictStr, AfterValidator(_endpoint)] = Field(alias="b")
    kind: Literal["import", "http"] = Field(alias="k")

    @computed_field
    @property
    def provenance(self) -> Literal["inferred"]:
        return "inferred"


class Route(_ArchitectureItem):
    id: Annotated[StrictStr, Field(pattern=r"^r:[0-9]+$")]
    method: WireLabel
    path: Annotated[StrictStr, Field(pattern=r"^/[\w/{}:.*@~+()-]*$")]
    file: CodePath | None = None

    @computed_field
    @property
    def provenance(self) -> Literal["inferred"]:
        return "inferred"

    @field_validator("path")
    @classmethod
    def _route_path(cls, value: str) -> str:
        if value.startswith("//") or {".", ".."}.intersection(value.split("/")):
            raise ValueError("expected an HTTP route path")
        return value


class ArchitectureDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    project: WireLabel | None = None
    nodes: tuple[Component, ...]
    files: tuple[ArchitectureFile, ...]
    routes: tuple[Route, ...] = ()
    links: tuple[ArchitectureLink, ...] = ()


def _unique(path: Path, field: str, values: tuple[str, ...]) -> None:
    seen = set()
    for i, value in enumerate(values):
        if value in seen:
            raise FloorplanError(path, field.format(i), "duplicate identifier")
        seen.add(value)


def load_architecture(path: Path, *, limit_kib: int | None = None) -> ArchitectureDocument:
    """Read the structured fields used by RepoIndex from a bounded graph."""
    data = _graph_document(path, limit_kib=limit_kib)
    # External links can contain remote URLs and are outside the architecture contract.
    links = data.get("links")
    if isinstance(links, list):
        data["links"] = [
            link for link in links if not isinstance(link, dict) or link.get("k") != "external"
        ]
    try:
        graph = ArchitectureDocument.model_validate(data)
    except ValidationError as exc:
        error = first_error(path, exc)
        raise FloorplanError(path, error.field, error.message) from None
    _unique(path, "nodes[{}].id", tuple(item.id for item in graph.nodes))
    _unique(path, "files[{}].p", tuple(item.path for item in graph.files))
    _unique(path, "routes[{}].id", tuple(item.id for item in graph.routes))
    return graph
