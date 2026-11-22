"""Compute the research-to-code trace of one feature (docs/TRACEABILITY.md).

Pure and read-only: nothing is stored. Link states (``gap``, ``built``, ``existing``,
``stale``, ``unverified``, ``missing``) are derived here against an optional Floorplan index.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from etat_major.floorplan import FloorplanIndex
from etat_major.overlay import resolve_file_path
from etat_major.records import ArchitectureLink, Decision, Feature, ResearchArtifact
from etat_major.refs import Ref
from etat_major.text_safety import bounded_repr
from etat_major.workspace import Workspace, link_warnings, linked_decisions

ARCHITECTURE_PROBLEM_STATES = frozenset({"stale", "gap"})


class TraceError(ValueError):
    """The requested trace cannot be produced."""


@dataclass(frozen=True)
class FindingLine:
    id: str
    text: str
    source: str | None
    unsourced: bool
    provenance: str


@dataclass(frozen=True)
class ResearchLine:
    ref: Ref
    found: bool
    status: str
    provenance: str
    title: str
    findings: tuple[FindingLine, ...]


@dataclass(frozen=True)
class Cite:
    ref: Ref
    state: str  # ok | unsourced | missing


@dataclass(frozen=True)
class DecisionLine:
    ref: Ref
    relation: str  # linked | related
    found: bool
    status: str
    provenance: str
    question: str
    cites: tuple[Cite, ...]


@dataclass(frozen=True)
class ArchLine:
    ref: Ref
    relation: str
    state: str
    provenance: str = "human"


@dataclass(frozen=True)
class AcceptanceLine:
    id: str
    text: str
    state: str = "open"
    provenance: str = "human"


@dataclass(frozen=True)
class LinkLine:
    ref: Ref
    state: str


@dataclass(frozen=True)
class Trace:
    feature: Feature
    research: tuple[ResearchLine, ...]
    decisions: tuple[DecisionLine, ...]
    architecture: tuple[ArchLine, ...]
    acceptance: tuple[AcceptanceLine, ...]
    links: tuple[LinkLine, ...]
    warnings: tuple[str, ...]

    @property
    def has_problems(self) -> bool:
        return (
            any(a.state in ARCHITECTURE_PROBLEM_STATES for a in self.architecture)
            or any(not r.found for r in self.research)
            or any(not d.found for d in self.decisions)
            or any(c.state == "missing" for d in self.decisions for c in d.cites)
        )


def _research_line(ref: Ref, research: ResearchArtifact | None) -> ResearchLine:
    if research is None:
        return ResearchLine(ref, False, "missing", "unverified", "", ())
    findings = tuple(
        FindingLine(f.id, f.text, f.source, research.is_unsourced(f), research.provenance)
        for f in research.findings
    )
    return ResearchLine(ref, True, research.status, research.provenance, research.title, findings)


def _cite(ws: Workspace, ref: Ref) -> Cite:
    research = ws.get_research(ref.id)
    if research is None:
        return Cite(ref, "missing")
    if ref.fragment is None:
        return Cite(ref, "ok")
    finding = next((f for f in research.findings if f.id == ref.fragment), None)
    if finding is None:
        return Cite(ref, "missing")
    return Cite(ref, "unsourced" if research.is_unsourced(finding) else "ok")


def _decision_line(ws: Workspace, d: Decision, relation: str) -> DecisionLine:
    cites = tuple(_cite(ws, r) for r in d.evidence)
    provenance = "human" if d.decided_by == "human" else "none"
    return DecisionLine(
        Ref("decision", d.id), relation, True, d.status, provenance, d.question, cites
    )


def _arch_state(
    link: ArchitectureLink, graph: FloorplanIndex | None, renames: Mapping[str, str] | None
) -> str:
    if graph is None or link.ref.kind == "trail":
        return "unverified"
    if link.ref.kind == "fp:f":
        present = graph.has_file(resolve_file_path(link.ref.id, graph, renames))
    else:
        present = graph.resolve(link.ref)
    if link.relation == "new":
        return "built" if present else "gap"
    return "existing" if present else "stale"


def _research_ids(feature: Feature, linked: tuple[Decision, ...]) -> list[str]:
    ids = [r.id for r in feature.research]
    ids += [e.id for d in linked for e in d.evidence]
    return list(dict.fromkeys(ids))


def _warnings(ws: Workspace, decisions: tuple[DecisionLine, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for line in decisions:
        if line.status != "approved":
            continue
        for cite in line.cites:
            research = ws.get_research(cite.ref.id)
            if research is not None and research.status == "unreviewed":
                out.append(
                    f"{line.ref} is approved but cites unreviewed {cite.ref.kind}:{cite.ref.id}"
                )
            if cite.state == "unsourced":
                out.append(f"{line.ref} is approved but cites unsourced finding {cite.ref}")
    return tuple(dict.fromkeys(out))


def _decision_lines(
    ws: Workspace, feature: Feature, research_ids: set[str]
) -> tuple[DecisionLine, ...]:
    linked = linked_decisions(ws, feature)
    lines = [_decision_line(ws, d, "linked") for d in linked]
    for ref in feature.decisions:
        if ws.get_decision(ref.id) is None:
            lines.append(DecisionLine(ref, "linked", False, "missing", "none", "", ()))
    linked_ids = {d.id for d in linked}
    lines += [
        _decision_line(ws, d, "related")
        for d in ws.decisions
        if d.id not in linked_ids and research_ids & {e.id for e in d.evidence}
    ]
    return tuple(lines)


def trace_feature(
    ws: Workspace,
    graph: FloorplanIndex | None,
    ref: Ref,
    *,
    renames: Mapping[str, str] | None = None,
) -> Trace:
    if ref.kind != "feature":
        raise TraceError(f"expected a feature reference, got {bounded_repr(str(ref))}")
    feature = ws.get_feature_by_ref(ref)
    if feature is None:
        raise TraceError(f"{bounded_repr(str(ref))} not found in the workspace")
    research_ids = _research_ids(feature, linked_decisions(ws, feature))
    research = tuple(
        _research_line(Ref("research", rid), ws.get_research(rid)) for rid in research_ids
    )
    decisions = _decision_lines(ws, feature, set(research_ids))
    return Trace(
        feature=feature,
        research=research,
        decisions=decisions,
        architecture=tuple(
            ArchLine(a.ref, a.relation, _arch_state(a, graph, renames))
            for a in feature.architecture
        ),
        acceptance=tuple(AcceptanceLine(a.id, a.text) for a in feature.acceptance),
        links=tuple(LinkLine(r, "unverified") for r in (*feature.tasks, *feature.milestones)),
        warnings=_warnings(ws, decisions) + tuple(map(str, link_warnings(ws, feature))),
    )
