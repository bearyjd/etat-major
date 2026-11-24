"""Project-local lookup for the recorded Understand inspector."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from etat_major.component_paths import component_file_path
from etat_major.localfiles import open_directory, open_relative_directory, read_text_kib
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import public_text, safe

if TYPE_CHECKING:
    from etat_major.components import Component, ComponentModel
    from etat_major.evidence import ArchitectureIndexes
    from etat_major.planning_view import PlanningInputs, SourceRow
    from etat_major.trail import Symbol, SymbolIndex

PAGE = 25
UNOWNED = "[Unowned files]"
TIES = "[Tied ownership]"


def token(kind: str, key: str) -> str:
    return "u-" + sha256(f"{kind}\0{key}".encode("utf-8", errors="surrogatepass")).hexdigest()[:32]


@dataclass(frozen=True)
class Artifact:
    label: str
    status: str
    freshness: str
    revision: str | None
    digest: str | None


@dataclass(frozen=True)
class Understand:
    project: str
    components: dict[str, Component]
    groups: tuple[str, ...]
    files: dict[str, tuple[str, ...]]
    owner: dict[str, str]
    ties: dict[str, tuple[str, ...]]
    symbols: dict[str, Symbol]
    symbol_pages: dict[str, int]
    lookup: dict[str, tuple[str, str]]
    trail: SymbolIndex | None
    artifacts: tuple[Artifact, Artifact]
    root: Path | None
    unmatchable: int


def _artifact(label, status, revision, source, digest):
    status = "present" if status == "recorded" else status
    if digest is None:
        return Artifact(label, status, "unknown", None, None)
    freshness = "unknown"
    if revision and source:
        freshness = "fresh" if revision == source else "stale"
    return Artifact(
        label,
        status,
        freshness,
        revision,
        digest,
    )


def bind_startup_revisions(view, startup: tuple[Artifact, ...]):
    """Only startup recording bytes carry the operator's configured revisions."""
    inspect = view._understand
    if inspect is None:
        return view
    trusted = {(a.label, a.digest, a.revision) for a in startup if a.digest}
    artifacts = tuple(
        a
        if (a.label, a.digest, a.revision) in trusted
        else replace(a, revision=None, freshness="unknown")
        for a in inspect.artifacts
    )
    return replace(view, _understand=replace(inspect, artifacts=artifacts))


def _groups(model, paths):
    files = defaultdict(list)
    owners = {}
    ties = {}
    unmatchable = 0
    lookup = model.ownership_lookup() if model else None
    for path in sorted(paths):
        try:
            owned = lookup(path) if lookup else None
        except ValueError:
            unmatchable += 1
            owned = None
        group = UNOWNED
        if owned and owned.component:
            group = owned.component.id
        elif owned and owned.ties:
            group = TIES
            ties[path] = owned.ties
        files[group].append(path)
        owners[path] = group
    return {k: tuple(v) for k, v in files.items()}, owners, ties, unmatchable


def _lookup(groups, owners, symbols):
    lookup = {}
    for kind, keys in (("component", groups), ("file", owners), ("symbol", symbols)):
        for key in keys:
            ident = token(kind, key)
            if ident in lookup:
                raise TaskFileError(Path("serve"), "selection", "opaque token collision")
            lookup[ident] = (kind, key)
    return lookup


def _symbol_pages(symbols):
    counts = defaultdict(int)
    symbol_pages = {}
    for key, symbol in sorted(symbols.items()):
        symbol_pages[key] = counts[symbol.path] // PAGE + 1
        counts[symbol.path] += 1
    return symbol_pages


def build(
    inputs: PlanningInputs,
    model: ComponentModel | None,
    indexes: ArchitectureIndexes,
    sources: list[SourceRow],
    digests: tuple[str | None, str | None],
) -> Understand:
    for name in ("source_revision", "trail_revision", "floorplan_revision"):
        rev = getattr(inputs, name)
        if rev is not None and not re.fullmatch(r"(?:[a-f0-9]{40}|[a-f0-9]{64})", rev):
            raise TaskFileError(Path("serve"), name, "expected a full Git commit SHA")
    paths = set(indexes.graph.file_paths) if indexes.graph else set()
    symbols = {}
    if indexes.trail:
        for s in indexes.trail.symbols:
            paths.add(s.path)
            symbols.setdefault(s.id, s)
    files, owners, ties, unmatchable = _groups(model, paths)
    components = {c.id: c for c in model.components} if model else {}
    groups = tuple(sorted(set(components) | set(files)))
    statuses = {r.label: r.status for r in sources}
    source = inputs.source_revision
    return Understand(
        inputs.project,
        components,
        groups,
        files,
        owners,
        ties,
        symbols,
        _symbol_pages(symbols),
        _lookup(groups, owners, symbols),
        indexes.trail,
        (
            _artifact(
                "Floorplan",
                statuses["Floorplan graph"],
                inputs.floorplan_revision,
                source,
                digests[0],
            ),
            _artifact("Trail", statuses["Trail wiring"], inputs.trail_revision, source, digests[1]),
        ),
        inputs.immutable_source,
        unmatchable,
    )


def excerpt(root: Path | None, freshness: str, symbol: Symbol) -> tuple[str, str]:
    if root is None:
        return "", "source.root: configure an immutable source snapshot to show an excerpt."
    if freshness != "fresh":
        return "", "source.revision: a matching recorded Trail revision is required."
    try:
        path = Path(component_file_path(symbol.path))
        if len(path.parts) > 64:
            raise ValueError
        with open_directory(root) as fd, open_relative_directory(path.parent, fd) as parent:
            source = read_text_kib(path, 256, dir_fd=parent)
    except (ValueError, OSError):
        return "", "source.file: expected a safe regular UTF-8 file of at most 256 KiB."
    lines = source.split("\n")
    if lines[-1] == "":
        lines.pop()
    start, end = symbol.start_line, symbol.end_line
    if not 1 <= start <= end <= len(lines):
        return "", "source.span: recorded lines fall outside the source file."
    selected = lines[start - 1 : min(end, start + 39)]
    raw = "\n".join(selected).encode()
    cleaned = "\n".join(safe(public_text(line, scp_remotes=True)) for line in selected)
    data = cleaned.encode()
    truncated = len(raw) > 8192 or len(data) > 8192 or end - start >= 40
    note = f"Lines {start}–{min(end, start + 39)}" + (" · truncated" if truncated else "")
    return data[:8192].decode("utf-8", errors="ignore"), note
