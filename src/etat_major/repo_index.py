"""Read-only repository snapshot joining independent architecture and symbol layers."""

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from etat_major.floorplan import (
    FLOORPLAN_COMMIT,
    SUPPORTED_SCHEMA,
    ArchitectureDocument,
    ArchitectureFile,
    ArchitectureLink,
    Component,
    Route,
    load_architecture,
)
from etat_major.refs import RefError, parse_ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import safe
from etat_major.trail import (
    TRAIL_VERSION,
    Symbol,
    SymbolEdge,
    SymbolIndex,
    TrailError,
    load_wiring,
    trail_symbol_path,
)

_LABEL = re.compile(r"[\w .@+$<>()\[\]!?,-]+")
_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


class RepoIndexError(TaskFileError):
    """Explicit metadata for an input pair is invalid."""


@dataclass(frozen=True)
class Indexer:
    layer: Literal["architecture", "symbols"]
    name: str
    provenance: Literal["human"] = "human"
    schema: str | None = None
    commit: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class Module:
    path: str
    imports: tuple[str, ...]
    kind: Literal["module"] = "module"
    layer: Literal["architecture"] = "architecture"
    provenance: Literal["inferred"] = "inferred"


@dataclass(frozen=True)
class ArchitectureLayer:
    components: tuple[Component, ...]
    files: tuple[ArchitectureFile, ...]
    links: tuple[ArchitectureLink, ...]
    routes: tuple[Route, ...]
    modules: tuple[Module, ...]


@dataclass(frozen=True)
class SymbolLayer:
    nodes: tuple[Symbol, ...]
    edges: tuple[SymbolEdge, ...]


@dataclass(frozen=True)
class Coverage:
    languages: tuple[str, ...]
    files_indexed: int
    files_skipped: int | None
    architecture_only: tuple[str, ...]
    symbols_only: tuple[str, ...]


@dataclass(frozen=True)
class RepoIndex:
    repository: str | None
    revision: str | None
    indexed_at: str | None
    indexers: tuple[Indexer, ...]
    coverage: Coverage
    architecture: ArchitectureLayer
    symbols: SymbolLayer
    version: Literal[1] = 1

    def files_with_symbols(self) -> tuple[ArchitectureFile, ...]:
        paths = {node.path for node in self.symbols.nodes if node.kind != "file"}
        return tuple(file for file in self.architecture.files if file.path in paths)

    def symbols_for_component(self, component_id: str) -> tuple[Symbol, ...]:
        if not any(component.id == component_id for component in self.architecture.components):
            return ()
        paths = {file.path for file in self.architecture.files if file.component_id == component_id}
        return tuple(
            node for node in self.symbols.nodes if node.path in paths and node.kind != "file"
        )

    def component_of(self, path: str) -> Component | None:
        owner = next(
            (file.component_id for file in self.architecture.files if file.path == path), None
        )
        return next(
            (component for component in self.architecture.components if component.id == owner), None
        )

    def to_data(self) -> dict[str, object]:
        """Return the exported version 1 snapshot."""
        architecture = self.architecture
        return {
            "version": self.version,
            "repository": self.repository,
            "revision": self.revision,
            "indexed_at": self.indexed_at,
            "indexers": [asdict(indexer) for indexer in self.indexers],
            "coverage": asdict(self.coverage),
            "architecture": {
                "components": [item.model_dump() for item in architecture.components],
                "files": [item.model_dump() for item in architecture.files],
                "links": [item.model_dump() for item in architecture.links],
                "routes": [item.model_dump() for item in architecture.routes],
                "modules": [asdict(module) for module in architecture.modules],
            },
            "symbols": {
                "nodes": [_symbol_record(node) for node in self.symbols.nodes],
                "edges": [_edge_record(edge) for edge in self.symbols.edges],
            },
        }

    def to_json(self) -> str:
        """Serialize this snapshot as stable version 1 JSON."""
        return json.dumps(self.to_data(), sort_keys=True, ensure_ascii=True, indent=2) + "\n"

    def to_text(self) -> str:
        """Render layer counts and the paths behind the coverage differences."""
        coverage = self.coverage
        lines = [
            f"Repository {self.repository or 'unknown'} at {self.revision or 'unknown'}",
            f"Indexed at {self.indexed_at or 'unknown'}",
            f"Architecture (Floorplan): {len(self.architecture.components)} components, "
            f"{len(self.architecture.files)} files, {len(self.architecture.links)} links, "
            f"{len(self.architecture.routes)} routes",
            f"Symbols (Trail): {len(self.symbols.nodes)} nodes, {len(self.symbols.edges)} edges",
            f"Coverage: {coverage.files_indexed} files, {len(self.files_with_symbols())} "
            "architecture files with symbols",
            "Architecture only: " + (", ".join(coverage.architecture_only) or "none"),
            "Symbols only: " + (", ".join(coverage.symbols_only) or "none"),
        ]
        return "\n".join(map(safe, lines)) + "\n"


def _symbol_record(symbol: Symbol) -> dict[str, object]:
    record = asdict(symbol)
    record["kind"] = safe(symbol.kind) if _LABEL.fullmatch(symbol.kind) else "unknown"
    record["range"] = [record.pop("start_line"), record.pop("end_line")]
    return record


def _edge_record(edge: SymbolEdge) -> dict[str, str]:
    return {
        "from": edge.source,
        "to": edge.target,
        "relation": edge.relation,
        "confidence": edge.confidence,
        "layer": edge.layer,
        "provenance": edge.provenance,
    }


def _trail_endpoint(value: str) -> bool:
    path, sep, symbol = value.partition("#")
    if not sep:
        path = path.removeprefix("node:")
    if ":" in path or any(char in symbol for char in "/\\%") or ":" in symbol.replace("::", ""):
        return False
    try:
        if sep:
            trail_symbol_path(value)
        else:
            parse_ref(f"trail:{path}#file")
    except RefError:
        return False
    return True


def _validate_trail(path: Path, trail: SymbolIndex) -> None:
    for i, node in enumerate(trail.symbols):
        if not _trail_endpoint(node.id):
            raise TrailError(path, f"nodes[{i}].id", "expected a file or symbol ID")
    for i, edge in enumerate(trail.edges):
        for field in ("source", "target", "relation", "confidence"):
            value = getattr(edge, field)
            valid = (
                _trail_endpoint(value) if field in {"source", "target"} else _LABEL.fullmatch(value)
            )
            if not valid:
                raise TrailError(path, f"edges[{i}].{field}", "invalid graph identifier")
    for i, language in enumerate(trail.coverage.languages):
        if not _LABEL.fullmatch(language):
            raise TrailError(path, f"meta.languages[{i}]", "invalid language identifier")


def _timestamp(path: Path, value: str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _TIMESTAMP.fullmatch(value):
        try:
            return datetime.fromisoformat(value).astimezone(UTC).isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError):
            pass
    raise RepoIndexError(path, "indexed_at", "expected an RFC 3339 timestamp")


def _modules(graph: ArchitectureDocument) -> tuple[Module, ...]:
    directories = {f"f:{file.path}": str(PurePosixPath(file.path).parent) for file in graph.files}
    imports: dict[str, set[str]] = {directory: set() for directory in directories.values()}
    for link in graph.links:
        source, target = directories.get(link.source), directories.get(link.target)
        if link.kind == "import" and source is not None and target is not None and source != target:
            imports[source].add(target)
    return tuple(Module(path, tuple(sorted(targets))) for path, targets in sorted(imports.items()))


def _coverage(graph: ArchitectureDocument, trail: SymbolIndex) -> Coverage:
    architecture = {file.path for file in graph.files}
    symbols = {node.path for node in trail.symbols}
    languages = {file.language for file in graph.files if file.language is not None}
    return Coverage(
        languages=tuple(sorted(languages.union(trail.coverage.languages))),
        files_indexed=len(architecture | symbols),
        files_skipped=None,
        architecture_only=tuple(sorted(architecture - symbols)),
        symbols_only=tuple(sorted(symbols - architecture)),
    )


def load_repo_index(
    graph_path: Path,
    trail_path: Path,
    *,
    revision: str | None = None,
    indexed_at: str | None = None,
) -> RepoIndex:
    """Read a pair of versioned artifacts supplied by the caller."""
    if revision is not None and (not isinstance(revision, str) or not _SHA.fullmatch(revision)):
        raise RepoIndexError(graph_path, "revision", "expected a full Git commit SHA")
    indexed_at = _timestamp(graph_path, indexed_at)
    graph = load_architecture(graph_path)
    trail = load_wiring(trail_path)
    _validate_trail(trail_path, trail)
    return RepoIndex(
        repository=graph.project,
        revision=revision,
        indexed_at=indexed_at,
        indexers=(
            Indexer("architecture", "floorplan", schema=SUPPORTED_SCHEMA, commit=FLOORPLAN_COMMIT),
            Indexer("symbols", "trail", version=TRAIL_VERSION),
        ),
        coverage=_coverage(graph, trail),
        architecture=ArchitectureLayer(
            components=tuple(sorted(graph.nodes, key=lambda node: node.id)),
            files=tuple(sorted(graph.files, key=lambda file: file.path)),
            links=tuple(
                sorted(graph.links, key=lambda link: (link.source, link.target, link.kind))
            ),
            routes=tuple(sorted(graph.routes, key=lambda route: route.id)),
            modules=_modules(graph),
        ),
        symbols=SymbolLayer(
            nodes=tuple(
                sorted(
                    trail.symbols,
                    key=lambda node: (node.id, node.start_line, node.end_line, node.kind),
                )
            ),
            edges=tuple(
                sorted(
                    trail.edges,
                    key=lambda edge: (edge.source, edge.target, edge.relation, edge.confidence),
                )
            ),
        ),
    )
