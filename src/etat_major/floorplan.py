"""Read-only reader for a Floorplan ``graph.json`` (schema ``floorplan/graph@1``).

Only component ids and file paths are kept. ``meta`` (absolute root, repo remotes) and every
other field are dropped on load so they can never be shown or stored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etat_major.localfiles import read_text
from etat_major.refs import Ref
from etat_major.text_safety import bounded_repr

SUPPORTED_SCHEMA = "floorplan/graph@1"


class FloorplanError(ValueError):
    """The graph file is unreadable or not a supported Floorplan graph."""


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


def _collect(path: Path, data: dict[str, Any], key: str, field: str) -> frozenset[str]:
    items = data.get(key)
    if not isinstance(items, list):
        raise FloorplanError(f"{path.name}: '{key}' must be a list")
    values: set[str] = set()
    for i, item in enumerate(items):
        value = item.get(field) if isinstance(item, dict) else None
        if not isinstance(value, str) or not value:
            raise FloorplanError(f"{path.name}: {key}[{i}] needs a non-empty string '{field}'")
        values.add(value)
    return frozenset(values)


def load_graph(path: Path) -> FloorplanIndex:
    try:
        text = read_text(path, 64)
    except (OSError, ValueError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        raise FloorplanError(f"{path.name}: cannot read graph file: {detail}") from exc
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise FloorplanError(f"{path.name}: graph file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FloorplanError(f"{path.name}: graph file must be a JSON object")
    if "schema" not in data:
        raise FloorplanError(
            f"{path.name}: missing 'schema'; only {SUPPORTED_SCHEMA!r} is supported"
        )
    if data["schema"] != SUPPORTED_SCHEMA:
        raise FloorplanError(
            f"{path.name}: unsupported schema {bounded_repr(data['schema'])}; "
            f"only {SUPPORTED_SCHEMA!r} is supported"
        )
    return FloorplanIndex(_collect(path, data, "nodes", "id"), _collect(path, data, "files", "p"))
