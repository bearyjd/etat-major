"""Classify Floorplan file ids against a blueprint and a code map."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from etat_major.floorplan import FloorplanIndex, FloorplanPlan

type FileState = Literal["planned-only", "built", "existing"]


def resolve_file_path(path: str, graph: FloorplanIndex, renames: Mapping[str, str] | None) -> str:
    """Use one rename between the two snapshots if its destination is indexed."""
    if renames is not None and (target := renames.get(path)) is not None and graph.has_file(target):
        return target
    return path


def classify_files(
    plan: FloorplanPlan, graph: FloorplanIndex, renames: Mapping[str, str] | None = None
) -> Mapping[str, FileState]:
    planned = {resolve_file_path(path, graph, renames) for path in plan.file_paths}
    classes: dict[str, FileState] = {f"f:{path}": "existing" for path in graph.file_paths - planned}
    for path in planned:
        classes[f"f:{path}"] = "built" if graph.has_file(path) else "planned-only"
    return MappingProxyType(classes)
