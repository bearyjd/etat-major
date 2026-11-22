"""Read-only readers for Floorplan code maps and blueprints.

Only component ids and file paths are kept. ``meta`` (absolute root, repo remotes) and every
other field are dropped on load so they can never be shown or stored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, field_validator

from etat_major.localfiles import open_directory, read_text
from etat_major.refs import Ref
from etat_major.taskfile import first_error
from etat_major.text_safety import bounded_repr, safe

SUPPORTED_SCHEMA = "floorplan/graph@1"
PLAN_SCHEMA = "floorplan/plan@1"
_LIMIT_MIB = 64
_SCHEMA_LABEL = re.compile(r"(?:floorplan/)?[a-zA-Z0-9_@.-]*")


class FloorplanError(ValueError):
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


def _collect(label: str, data: dict[str, Any], key: str, field: str) -> frozenset[str]:
    items = data.get(key)
    if not isinstance(items, list):
        raise FloorplanError(f"{label}: '{key}' must be a list")
    values: set[str] = set()
    for i, item in enumerate(items):
        value = item.get(field) if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise FloorplanError(f"{label}: {key}[{i}] needs a non-empty string '{field}'")
        if key == "files" and not _is_relative_path(value):
            raise FloorplanError(f"{label}: {key}[{i}].{field} must be repository-relative")
        values.add(value)
    return frozenset(values)


def load_graph(path: Path) -> FloorplanIndex:
    label = safe(path.name, limit=100)
    data = _read_json(path)
    if "schema" not in data:
        raise FloorplanError(f"{label}: missing 'schema'; only {SUPPORTED_SCHEMA!r} is supported")
    schema = data["schema"]
    if schema != SUPPORTED_SCHEMA:
        detail = " " + bounded_repr(schema)
        if isinstance(schema, str) and not _SCHEMA_LABEL.fullmatch(schema):
            detail = ""
        raise FloorplanError(
            f"{label}: unsupported schema{detail}; only {SUPPORTED_SCHEMA!r} is supported"
        )
    return FloorplanIndex(_collect(label, data, "nodes", "id"), _collect(label, data, "files", "p"))


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _read_json(path: Path) -> dict[str, Any]:
    label = safe(path.name, limit=100)
    try:
        with open_directory(path.parent) as fd:
            text = read_text(path, _LIMIT_MIB, dir_fd=fd)
    except (OSError, UnicodeError):
        raise FloorplanError(f"{label}: JSON: cannot read file as UTF-8") from None
    except ValueError as exc:
        raise FloorplanError(f"{label}: JSON: cannot read file: {safe(exc)}") from None
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        raise FloorplanError(f"{label}: JSON: invalid JSON") from None
    if not isinstance(data, dict):
        raise FloorplanError(f"{label}: JSON: expected an object")
    return data


def load_plan(path: Path) -> FloorplanPlan:
    """Validate a Floorplan blueprint and keep only its planned file paths."""
    data = _read_json(path)
    for key in ("$schema", "schema"):
        if key in data and data[key] != PLAN_SCHEMA:
            raise FloorplanError(f"{safe(path.name)}: {key}: expected {PLAN_SCHEMA}")
    try:
        plan = _PlanDocument.model_validate(data)
    except ValidationError as exc:
        raise FloorplanError(safe(first_error(path, exc))) from None
    return FloorplanPlan(frozenset(file.path for file in plan.files))
