"""Read a Trail 0.30.5 wiring graph into a read-only symbol index."""

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from etat_major.localfiles import open_directory, read_text
from etat_major.refs import RefError, parse_ref
from etat_major.taskfile import Text, first_error
from etat_major.text_safety import safe

_LIMIT_MIB = 64
_SPAN = re.compile(r"L([0-9]+)-L([0-9]+)")
_RELATIONS = frozenset({"calls", "contains", "imports", "extends", "references", "implements"})
_VERIFIED = frozenset({"extracted", "lsp_resolved"})
_CONFIDENCES = _VERIFIED | {"inferred", "lsp_dispatch"}
type NodeKind = Literal["file", "class", "function", "method"]


class TrailError(ValueError):
    """A Trail artifact is unreadable or invalid."""


@dataclass(frozen=True)
class Symbol:
    id: str
    kind: NodeKind
    path: str
    start_line: int
    end_line: int


class _WireModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class SymbolEdge(_WireModel):
    source: Text
    target: Text
    relation: StrictStr
    confidence: StrictStr

    @property
    def provenance(self) -> Literal["verified", "inferred"]:
        return "verified" if self.confidence in _VERIFIED else "inferred"

    @property
    def unknown_relation(self) -> bool:
        return self.relation not in _RELATIONS

    @property
    def unknown_confidence(self) -> bool:
        return self.confidence not in _CONFIDENCES


@dataclass(frozen=True)
class SymbolCoverage:
    languages: tuple[str, ...]
    node_kinds: Mapping[str, int]
    relations: Mapping[str, int]
    files_without_symbols: frozenset[str]


@dataclass(frozen=True)
class SymbolIndex:
    symbols: tuple[Symbol, ...]
    edges: tuple[SymbolEdge, ...]
    coverage: SymbolCoverage
    indexed_revision: str | None = None

    def symbols_in(self, path: str) -> tuple[Symbol, ...]:
        return tuple(symbol for symbol in self.symbols if symbol.path == path)

    def callers(self, symbol_id: str) -> tuple[SymbolEdge, ...]:
        return tuple(
            edge for edge in self.edges if edge.relation == "calls" and edge.target == symbol_id
        )

    def callees(self, symbol_id: str) -> tuple[SymbolEdge, ...]:
        return tuple(
            edge for edge in self.edges if edge.relation == "calls" and edge.source == symbol_id
        )

    def has_symbol(self, symbol_id: str) -> bool:
        return any(symbol.id == symbol_id for symbol in self.symbols)

    def freshness(self, current_revision: str | None) -> Literal["fresh", "stale", "unknown"]:
        if not self.indexed_revision or not current_revision:
            return "unknown"
        return "fresh" if self.indexed_revision == current_revision else "stale"


class _Node(_WireModel):
    path: StrictStr
    kind: NodeKind
    id: Text
    span: tuple[int, int]

    @field_validator("path")
    @classmethod
    def _check_path(cls, path: str) -> str:
        try:
            parse_ref(f"fp:f:{path}")
        except RefError:
            raise ValueError("expected a repository-relative code path") from None
        return path

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str, info: ValidationInfo) -> str:
        path, kind = info.data.get("path"), info.data.get("kind")
        if kind == "file" and value == path:
            return value
        if kind != "file":
            try:
                if parse_ref(f"trail:{value}").id == path:
                    return value
            except RefError:
                pass
        raise ValueError("expected the file path or a symbol ID in that path")

    @field_validator("span", mode="before")
    @classmethod
    def _parse_span(cls, value: object) -> tuple[int, int]:
        match = _SPAN.fullmatch(value) if isinstance(value, str) else None
        if match:
            start, end = int(match[1]), int(match[2])
            if 1 <= start <= end:
                return start, end
        raise ValueError("expected an inclusive L<start>-L<end> span with positive ordered lines")


class _Meta(_WireModel):
    languages: tuple[Text, ...] = ()


class _Wiring(_WireModel):
    meta: _Meta
    nodes: tuple[_Node, ...]
    edges: tuple[SymbolEdge, ...]


def _coverage(wiring: _Wiring) -> SymbolCoverage:
    files = {node.path for node in wiring.nodes if node.kind == "file"}
    with_symbols = {node.path for node in wiring.nodes if node.kind != "file"}
    return SymbolCoverage(
        wiring.meta.languages,
        MappingProxyType(dict(Counter(node.kind for node in wiring.nodes))),
        MappingProxyType(dict(Counter(edge.relation for edge in wiring.edges))),
        frozenset(files - with_symbols),
    )


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _read_wiring(path: Path) -> _Wiring:
    label = safe(path.name, limit=100)
    try:
        with open_directory(path.parent) as fd:
            text = read_text(path, _LIMIT_MIB, dir_fd=fd)
    except (OSError, UnicodeError):
        raise TrailError(f"{label}: JSON: cannot read file as UTF-8") from None
    except ValueError as exc:
        raise TrailError(f"{label}: JSON: cannot read file: {safe(exc)}") from None
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise TrailError(f"{label}: JSON: invalid JSON") from None
    if not isinstance(data, dict):
        raise TrailError(f"{label}: JSON: expected an object")
    meta = data.get("meta")
    version = meta.get("version") if isinstance(meta, dict) else None
    if type(version) is not int or version != 1:
        raise TrailError(f"{label}: meta.version: only integer version 1 is supported")
    try:
        return _Wiring.model_validate(data)
    except ValidationError as exc:
        raise TrailError(safe(first_error(Path(label), exc))) from None


def load_wiring(path: Path, *, indexed_revision: str | None = None) -> SymbolIndex:
    """Read a bounded wiring.json graph. Revision is supplied by the caller."""
    wiring = _read_wiring(path)
    symbols = tuple(Symbol(node.id, node.kind, node.path, *node.span) for node in wiring.nodes)
    return SymbolIndex(symbols, wiring.edges, _coverage(wiring), indexed_revision)
