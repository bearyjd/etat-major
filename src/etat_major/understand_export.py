"""Build the Understand export from the component model and recorded indexes.

The shape and its limits are fixed by ``docs/contracts/understand-export.md``.
Nothing here runs Git or a tool, and no navigation state is exported.
"""

import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from etat_major.component_paths import component_file_path
from etat_major.components import MAX_PROJECT_ID_LENGTH, ComponentModel
from etat_major.planning_issues import (
    RefreshIssueLog,
    issue_summary,
    planning_path,
    planning_text,
    project_issue_filter,
    public_issue,
)
from etat_major.planning_view import (
    PlanningInputs,
    SourceRow,
    _component_rows,
    _load_component_model,
    _load_indexes,
)
from etat_major.refs import PROJECT_ID
from etat_major.taskfile import TaskFileError
from etat_major.trail import _CONFIDENCES, _NODE_KINDS, _RELATIONS
from etat_major.understand import TIES, UNOWNED, Understand, build
from etat_major.workspace import Issue, load_workspace

UNDERSTAND_SCHEMA = "etat-major/understand@1"
# Component and path caps are enforced by the component loader.
MAX_FILES = 20_000
MAX_ISSUES = 200
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
NOTES = (
    "Trail's cross-module Kotlin calls were weak on the measured sample.",
    "Trail imports are unresolved for Kotlin.",
)
_COMPONENT_KEYS = (
    "id",
    "label",
    "kind",
    "parent",
    "owner",
    "summary",
    "summary_provenance",
    "provenance",
    "reviewed",
)


@dataclass(frozen=True)
class _Inventory:
    """Recorded paths, each with the exported name of its ownership group."""

    owners: dict[str, str]
    unmatchable: frozenset[str]
    groups: tuple[str, ...]


def _has_records(workspace, project: str) -> bool:
    return (
        any(feature.project == project for feature in workspace.features)
        or any(task.project == project for task in workspace.tasks)
        or any(owner == project for owner, _ in workspace.milestones)
    )


def _load(inputs: PlanningInputs) -> tuple[ComponentModel | None, Understand, list[Issue]]:
    """The narrow loader, repeating the safeguards of ``load_planning_view``."""
    project = inputs.project
    if len(project) > MAX_PROJECT_ID_LENGTH or not re.fullmatch(PROJECT_ID, project):
        raise TaskFileError(Path("serve"), "project", "expected a project identifier")
    shared: Counter[str] = Counter()
    issue_filter = project_issue_filter(project, shared, RefreshIssueLog())
    workspace = load_workspace(inputs.workspace, issue_filter=issue_filter)
    issues = [*workspace.issues, *issue_summary(shared, workspace.omitted_issues)]
    sources: list[SourceRow] = []
    model = _load_component_model(inputs, sources, issues)
    if model is None and not _has_records(workspace, project):
        raise TaskFileError(Path("serve"), "project", "no records for the configured project")
    indexes, digests = _load_indexes(inputs, sources, issues)
    view = build(inputs, model, indexes, sources, digests)
    if model is None and all(artifact.status == "missing" for artifact in view.artifacts):
        raise TaskFileError(
            Path("serve"), "components", "no component model loaded and no recorded artifact exists"
        )
    return model, view, issues


def _listable(path: str) -> bool:
    try:
        component_file_path(path)
    except ValueError:
        return False
    return planning_path(path) != "[redacted location]"


def _inventory(view: Understand) -> _Inventory:
    def public(group: str) -> str:
        return group if group in (UNOWNED, TIES) else f"{view.project}/{group}"

    unmatchable = frozenset(path for path in view.owner if not _listable(path))
    owners = {
        path: UNOWNED if path in unmatchable else public(group)
        for path, group in view.owner.items()
    }
    groups = (*sorted(map(public, view.components)), UNOWNED, TIES)
    return _Inventory(owners, unmatchable, groups)


def _artifacts(view: Understand, keys: tuple[str, ...]) -> list[dict]:
    return [{key: getattr(artifact, key) for key in keys} for artifact in view.artifacts]


def _coverage(view: Understand, inventory: _Inventory) -> dict:
    counts = Counter(inventory.owners.values())
    total = len(inventory.owners)
    present = any(artifact.status == "present" for artifact in view.artifacts)
    return {
        "inventory": "available" if present else "unavailable",
        "owned": total - counts[UNOWNED] - counts[TIES],
        "unowned": counts[UNOWNED],
        "tied": counts[TIES],
        "total": total,
        "unmatchable_paths": len(inventory.unmatchable),
        "artifacts": _artifacts(view, ("label", "status", "freshness")),
        "notes": list(NOTES),
    }


def _bucket(kinds: Counter[str], edges: Counter[tuple[str, str]]) -> dict:
    nested: dict[str, dict[str, int]] = defaultdict(dict)
    for (relation, confidence), count in edges.items():
        nested[relation][confidence] = count
    return {"count": kinds.total(), "kinds": dict(kinds), "edges": dict(nested)}


def _known(value: str, known: frozenset[str]) -> str:
    return value if value in known else "unknown"


def _tallies(view: Understand, inventory: _Inventory) -> dict:
    """Count symbols by their file's owner and edges by their source symbol's owner."""
    kinds: defaultdict[str | None, Counter] = defaultdict(Counter)
    edges: defaultdict[str | None, Counter] = defaultdict(Counter)
    total_kinds: Counter[str] = Counter()
    total_edges: Counter[tuple[str, str]] = Counter()
    for symbol in view.symbols.values():
        kind = _known(symbol.kind, _NODE_KINDS)
        total_kinds[kind] += 1
        kinds[inventory.owners[symbol.path]][kind] += 1
    unresolved = 0
    for edge in view.trail.edges if view.trail else ():
        key = (_known(edge.relation, _RELATIONS), _known(edge.confidence, _CONFIDENCES))
        total_edges[key] += 1
        source = view.symbols.get(edge.source)
        if source is None:
            unresolved += 1
        else:
            edges[inventory.owners[source.path]][key] += 1
    return {
        "total": _bucket(total_kinds, total_edges),
        "by_component": {g: _bucket(kinds[g], edges[g]) for g in inventory.groups},
        "unresolved_source": unresolved,
    }


def _names(values: Iterable[str]) -> list[str]:
    return sorted({planning_text(value) for value in set(values)})


def _symbols(view: Understand, inventory: _Inventory) -> dict:
    coverage = view.trail.coverage if view.trail else None
    edges = view.trail.edges if view.trail else ()
    unresolved: Counter[str] = Counter()
    for relation, count in coverage.unresolved_relations.items() if coverage else ():
        unresolved[_known(relation, _RELATIONS)] += count
    return {
        **_tallies(view, inventory),
        "unresolved_relations": dict(unresolved),
        "unknown_kinds": _names(coverage.unknown_kinds if coverage else ()),
        "unknown_relations": _names(e.relation for e in edges if e.unknown_relation),
        "unknown_confidences": _names(e.confidence for e in edges if e.unknown_confidence),
        "languages": _names(coverage.languages if coverage else ()),
        "module_scopes": _names(coverage.module_scopes if coverage else ()),
        "files_without_symbols": len(coverage.files_without_symbols) if coverage else 0,
    }


def _components(
    model: ComponentModel | None, inventory: _Inventory, by_component: dict
) -> list[dict]:
    files = Counter(inventory.owners.values())
    rows = [
        {
            **{key: getattr(row, key) for key in _COMPONENT_KEYS},
            "paths": list(row.paths),
            "files": files[row.id],
            "symbols": by_component[row.id]["count"],
        }
        for row in _component_rows(model)
    ]
    return sorted(rows, key=lambda row: row["id"])


def _file_lists(view: Understand, inventory: _Inventory) -> tuple[dict, list[str]]:
    """The opt-in file keys, plus the capped list of files without symbols."""
    listed = sorted(
        (group, planning_path(path), path)
        for path, group in inventory.owners.items()
        if path not in inventory.unmatchable
    )
    files: dict[str, list[str]] = {group: [] for group in inventory.groups}
    ties = []
    for group, public, path in listed[:MAX_FILES]:
        files[group].append(public)
        if group == TIES:
            rivals = sorted(f"{view.project}/{ident}" for ident in view.ties[path])
            ties.append({"path": public, "components": rivals})
    empty = view.trail.coverage.files_without_symbols if view.trail else frozenset()
    bare = sorted(planning_path(path) for path in empty - inventory.unmatchable)
    truncated = len(listed) > MAX_FILES or len(bare) > MAX_FILES
    ties.sort(key=lambda tie: tie["path"])
    return {"files": files, "ties": ties, "files_truncated": truncated}, bare[:MAX_FILES]


def _warnings(inputs: PlanningInputs, view: Understand) -> list[Issue]:
    warnings = []
    flags = (("graph", inputs.graph), ("trail", inputs.trail))
    for (name, path), artifact in zip(flags, view.artifacts, strict=True):
        if path is None:
            message = "no recording supplied for this artifact"
            warnings.append(Issue(name, "file", message, "warning", False))
        elif artifact.freshness == "stale":
            message = "recorded revision differs from the source revision"
            warnings.append(Issue(name, "revision", message, "warning", False))
    return warnings


def _issue_order(issue: Issue) -> tuple:
    return (issue.path, issue.field, issue.message, issue.severity, issue.blocking)


def _issue_rows(own: list[Issue], read: list[Issue]) -> dict:
    """Keep the export's own warnings, then read errors, then the rest, up to the cap."""
    ranked = sorted(map(public_issue, read), key=lambda i: (i.severity != "error", _issue_order(i)))
    every = [*map(public_issue, own), *ranked]
    kept = sorted(every[:MAX_ISSUES], key=_issue_order)
    keys = ("path", "field", "message", "severity", "blocking")
    return {
        "issues": [{key: getattr(issue, key) for key in keys} for issue in kept],
        "omitted_issues": len(every) - len(kept),
    }


def understand_payload(inputs: PlanningInputs, *, include_files: bool = False) -> dict:
    model, view, read = _load(inputs)
    inventory = _inventory(view)
    symbols = _symbols(view, inventory)
    own = _warnings(inputs, view)
    extra = {}
    if include_files:
        extra, symbols["files_without_symbols_paths"] = _file_lists(view, inventory)
        if extra["files_truncated"]:
            message = f"file lists truncated at {MAX_FILES} paths"
            own.append(Issue("files", "files", message, "warning", False))
    return {
        "schema": UNDERSTAND_SCHEMA,
        "version": 1,
        "project": view.project,
        "artifacts": _artifacts(view, ("label", "status", "freshness", "revision", "digest")),
        "coverage": _coverage(view, inventory),
        "components": _components(model, inventory, symbols["by_component"]),
        "symbols": symbols,
        **extra,
        **_issue_rows(own, read),
    }


def understand_document(inputs: PlanningInputs, *, include_files: bool = False) -> str:
    """The exact bytes of the export, shared by every caller; never cut to fit."""
    payload = understand_payload(inputs, include_files=include_files)
    document = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    if len(document.encode()) > MAX_DOCUMENT_BYTES:
        message = f"output exceeds the {MAX_DOCUMENT_BYTES} byte whole-document cap"
        raise TaskFileError(Path("serve"), "document", message)
    return document
