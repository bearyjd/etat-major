"""Read a Trail 0.30.5 wiring graph into a read-only symbol index."""

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
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
from etat_major.taskfile import TaskFileError, Text, check_recorded_array, first_error

TRAIL_VERSION = "0.30.5"
_LIMIT_MIB = 64
_SPAN = re.compile(r"L([0-9]+)-L([0-9]+)")
_BACKTICKED = re.compile(r"`[^`]*`")
_NODE_KINDS = frozenset(
    {
        "file", "class", "function", "method", "interface", "type", "enum",
        "struct", "trait", "module", "constant", "variable",
    }
)  # fmt: skip
_RELATIONS = frozenset({"calls", "contains", "imports", "extends", "references", "implements"})
_VERIFIED = frozenset({"extracted", "lsp_resolved"})
_CONFIDENCES = _VERIFIED | {"inferred", "lsp_dispatch"}


class TrailError(TaskFileError):
    """A Trail artifact is unreadable or invalid."""


@dataclass(frozen=True)
class Symbol:
    id: str
    kind: str
    path: str
    start_line: int
    end_line: int
    layer: Literal["symbols"] = "symbols"
    provenance: Literal["verified"] = "verified"

    @property
    def unknown_kind(self) -> bool:
        return self.kind not in _NODE_KINDS


class _WireModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class SymbolEdge(_WireModel):
    source: Text
    target: Text
    relation: StrictStr
    confidence: StrictStr

    @property
    def layer(self) -> Literal["symbols"]:
        return "symbols"

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
    unknown_kinds: frozenset[str]
    unresolved_relations: Mapping[str, int]
    module_scopes: tuple[str, ...]


@dataclass(frozen=True)
class SymbolIndex:
    symbols: tuple[Symbol, ...]
    edges: tuple[SymbolEdge, ...]
    coverage: SymbolCoverage
    indexed_revision: str | None = None
    _symbol_ids: frozenset[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_symbol_ids", frozenset(symbol.id for symbol in self.symbols))

    @property
    def module_scopes(self) -> tuple[str, ...]:
        return self.coverage.module_scopes

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
        return symbol_id in self._symbol_ids

    def freshness(self, current_revision: str | None) -> Literal["fresh", "stale", "unknown"]:
        if not self.indexed_revision or not current_revision:
            return "unknown"
        return "fresh" if self.indexed_revision == current_revision else "stale"


def trail_symbol_path(symbol_id: str) -> str:
    """Validate a graph symbol ID and return its repository-relative path."""
    path, sep, fragment = symbol_id.partition("#")
    # Kotlin permits spaces inside backticked names. Validate without changing the stored ID.
    fragment = _BACKTICKED.sub(lambda match: match[0].replace(" ", "_"), fragment)
    return parse_ref(f"trail:{path}{sep}{fragment}").id


class _Node(_WireModel):
    path: StrictStr
    kind: StrictStr
    id: Text
    span: tuple[int, int]

    @field_validator("path")
    @classmethod
    def _check_path(cls, path: str) -> str:
        try:
            parse_ref(f"trail:{path}#file")
        except RefError:
            raise ValueError("expected a repository-relative code path") from None
        return path

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str, info: ValidationInfo) -> str:
        path, kind = info.data.get("path"), info.data.get("kind")
        if value == path and (kind == "file" or kind not in _NODE_KINDS):
            return value
        if kind != "file":
            try:
                if trail_symbol_path(value) == path:
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


class _Scope(_WireModel):
    prefix: StrictStr

    @field_validator("prefix")
    @classmethod
    def _check_prefix(cls, prefix: str) -> str:
        if not prefix:
            return prefix
        try:
            if ":" not in prefix:
                parse_ref(f"trail:{prefix}#scope")
                return prefix
        except RefError:
            pass
        raise ValueError("expected a repository-relative scope prefix or an empty root prefix")


class _Meta(_WireModel):
    languages: tuple[Text, ...] = ()
    scopes: tuple[_Scope, ...] = ()


class _Wiring(_WireModel):
    meta: _Meta
    nodes: tuple[_Node, ...]
    edges: tuple[SymbolEdge, ...]


def _coverage(wiring: _Wiring) -> SymbolCoverage:
    files = {node.path for node in wiring.nodes if node.kind == "file"}
    with_symbols = {node.path for node in wiring.nodes if node.kind != "file"}
    ids = {node.id for node in wiring.nodes}
    kinds = Counter(node.kind for node in wiring.nodes)
    unresolved = Counter(edge.relation for edge in wiring.edges if edge.target not in ids)
    return SymbolCoverage(
        languages=wiring.meta.languages,
        node_kinds=MappingProxyType(dict(kinds)),
        relations=MappingProxyType(dict(Counter(edge.relation for edge in wiring.edges))),
        files_without_symbols=frozenset(files - with_symbols),
        unknown_kinds=frozenset(kinds.keys() - _NODE_KINDS),
        unresolved_relations=MappingProxyType(dict(unresolved)),
        module_scopes=tuple(scope.prefix for scope in wiring.meta.scopes),
    )


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _read_wiring(path: Path) -> _Wiring:
    try:
        with open_directory(path.parent) as fd:
            text = read_text(path, _LIMIT_MIB, dir_fd=fd)
    except (OSError, UnicodeError):
        raise TrailError(path, "JSON", "cannot read file as UTF-8") from None
    except ValueError as exc:
        raise TrailError(path, "JSON", f"cannot read file: {exc}") from None
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise TrailError(path, "JSON", "invalid JSON") from None
    if not isinstance(data, dict):
        raise TrailError(path, "JSON", "expected an object")
    meta = data.get("meta")
    version = meta.get("version") if isinstance(meta, dict) else None
    if type(version) is not int or version != 1:
        raise TrailError(path, "meta.version", "only integer version 1 is supported")
    for key in ("nodes", "edges"):
        check_recorded_array(path, key, data.get(key), error=TrailError)
    check_recorded_array(path, "meta.languages", meta.get("languages"), error=TrailError)
    check_recorded_array(path, "meta.scopes", meta.get("scopes"), error=TrailError)
    try:
        return _Wiring.model_validate(data)
    except ValidationError as exc:
        error = first_error(path, exc)
        raise TrailError(path, error.field, error.message) from None


def load_wiring(path: Path, *, indexed_revision: str | None = None) -> SymbolIndex:
    """Read a bounded wiring.json graph. Revision is supplied by the caller."""
    wiring = _read_wiring(path)
    symbols = tuple(Symbol(node.id, node.kind, node.path, *node.span) for node in wiring.nodes)
    return SymbolIndex(symbols, wiring.edges, _coverage(wiring), indexed_revision)
