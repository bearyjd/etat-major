"""Read-only Discover view model: research and decisions, labelled and bounded."""

from dataclasses import dataclass, replace
from datetime import date

from etat_major.planning_issues import planning_text
from etat_major.records import Decision, ResearchArtifact
from etat_major.text_safety import public_source_url
from etat_major.trace import cite
from etat_major.workspace import Workspace

MAX_QUERY = 128
MAX_RESEARCH = 200
MAX_DECISIONS = 200
MAX_FINDINGS = 50
MAX_ALTERNATIVES = 20
MAX_CITES = 20
MAX_FEATURES = 20


@dataclass(frozen=True)
class FindingRow:
    id: str
    text: str
    source: str | None
    source_date: date | None
    unsourced: bool


@dataclass(frozen=True)
class ResearchRow:
    id: str
    title: str
    status: str
    provenance: str
    project: str | None
    findings: tuple[FindingRow, ...]
    omitted_findings: int
    features: tuple[str, ...]


@dataclass(frozen=True)
class CiteRow:
    ref: str
    state: str  # ok | unsourced | missing: the citation resolves, nothing more
    status: str  # the cited research's own status, empty when missing
    provenance: str


@dataclass(frozen=True)
class DecisionRow:
    id: str
    question: str
    status: str
    decided_on: date | None
    chosen: str | None
    rationale: str | None
    alternatives: tuple[tuple[str, str], ...]
    omitted_alternatives: int
    cites: tuple[CiteRow, ...]
    omitted_cites: int
    features: tuple[str, ...]


@dataclass(frozen=True)
class DiscoverView:
    research: tuple[ResearchRow, ...]
    decisions: tuple[DecisionRow, ...]
    omitted_research: int = 0
    omitted_decisions: int = 0
    issue_count: int = 0
    query: str = ""

    @property
    def has_data(self) -> bool:
        return bool(self.research or self.decisions or self.issue_count)


def _text(value: str) -> str:
    return planning_text(value)


def _feature_labels(ws: Workspace, kind: str, record_id: str, direct) -> tuple[str, ...]:
    labels = {str(ref.project) + "/" + ref.id for ref in direct}
    for feature in ws.features:
        refs = feature.research if kind == "research" else feature.decisions
        if any(ref.id == record_id for ref in refs):
            labels.add(f"{feature.project}/{feature.id}")
    return tuple(sorted(labels)[:MAX_FEATURES])


def _finding(research: ResearchArtifact, finding) -> FindingRow:
    dates = {s.url: s.date for s in research.sources}
    unsourced = research.is_unsourced(finding)
    source = None if finding.source is None else public_source_url(finding.source)
    return FindingRow(
        finding.id,
        _text(finding.text),
        source,
        None if unsourced else dates.get(finding.source),
        unsourced,
    )


def _research_row(ws: Workspace, research: ResearchArtifact) -> ResearchRow:
    findings = tuple(_finding(research, f) for f in research.findings[:MAX_FINDINGS])
    return ResearchRow(
        research.id,
        _text(research.title),
        research.status,
        research.provenance,
        research.project,
        findings,
        max(0, len(research.findings) - MAX_FINDINGS),
        _feature_labels(ws, "research", research.id, ()),
    )


def _cite_row(ws: Workspace, ref) -> CiteRow:
    found = ws.get_research(ref.id)
    state = cite(ws, ref).state
    return CiteRow(
        _text(str(ref)), state, found.status if found else "", found.provenance if found else ""
    )


def _decision_row(ws: Workspace, d: Decision) -> DecisionRow:
    alternatives = tuple((_text(a.option), _text(a.why_not)) for a in d.alternatives)
    return DecisionRow(
        d.id,
        _text(d.question),
        d.status,
        d.decided_on,
        _text(d.chosen) if d.chosen else None,
        _text(d.rationale) if d.rationale else None,
        alternatives[:MAX_ALTERNATIVES],
        max(0, len(alternatives) - MAX_ALTERNATIVES),
        tuple(_cite_row(ws, r) for r in d.evidence[:MAX_CITES]),
        max(0, len(d.evidence) - MAX_CITES),
        _feature_labels(ws, "decision", d.id, d.features),
    )


def _failed_records(ws: Workspace) -> int:
    shared = ("decisions", "research", "decision:", "research:")
    return sum(
        1 for issue in ws.issues if issue.severity == "error" and issue.path.startswith(shared)
    )


def build_discover(ws: Workspace, filtered_issues: int = 0) -> DiscoverView:
    """``filtered_issues`` counts decision/research issues the project filter moved out of ws."""
    return DiscoverView(
        tuple(_research_row(ws, r) for r in ws.research[:MAX_RESEARCH]),
        tuple(_decision_row(ws, d) for d in ws.decisions[:MAX_DECISIONS]),
        max(0, len(ws.research) - MAX_RESEARCH),
        max(0, len(ws.decisions) - MAX_DECISIONS),
        _failed_records(ws) + filtered_issues,
    )


def _searchable(row: DecisionRow) -> str:
    parts = [row.id, row.question, row.status, row.chosen or "", row.rationale or ""]
    parts.extend(part for pair in row.alternatives for part in pair)
    return "\n".join(parts).casefold()


def filter_decisions(view: DiscoverView, query: str) -> DiscoverView:
    if len(query) > MAX_QUERY or not query.isprintable() or "�" in query:
        raise ValueError("invalid query")
    needle = query.strip().casefold()
    rows = tuple(d for d in view.decisions if needle in _searchable(d))
    return replace(view, decisions=rows, query=query)
