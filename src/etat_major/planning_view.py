"""Build a sanitized, project-scoped snapshot from local intent and recorded evidence."""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from functools import partial
from pathlib import Path
from typing import Literal

from etat_major.components import MAX_PROJECT_ID_LENGTH, ComponentModel, load_components
from etat_major.components_seed import PROPOSAL_KIND
from etat_major.evidence import (
    ArchitectureIndexes,
    ProgressEvidence,
    ProgressReport,
    Rung,
    derive_progress,
)
from etat_major.evidence_git import EMPTY_GIT_EVIDENCE, load_git
from etat_major.evidence_records import GeneratedArtifact, load_prs, load_releases
from etat_major.execution_links import (
    EXECUTION_LINKS_LABEL,
    ExecutionLinks,
    codeman_origin,
    load_execution_links,
)
from etat_major.floorplan import load_graph
from etat_major.localfiles import entry_mode, open_directory
from etat_major.manual_review import MANUAL_REVIEW_LABEL, ManualReview, load_manual_review
from etat_major.meute import MeuteEvidence, MeuteSnapshot, load_meute
from etat_major.planning_issues import (
    issue_summary,
    planning_path,
    planning_text,
    project_issue_filter,
    public_issue,
)
from etat_major.records import Feature
from etat_major.refs import PROJECT_ID, Ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import safe
from etat_major.trace import trace_feature
from etat_major.trail import load_wiring
from etat_major.workspace import Issue, Workspace, feature_ref, load_workspace

MEUTE_SOURCE_LABEL = "Meute reports"


@dataclass(frozen=True)
class PlanningInputs:
    workspace: Path
    project: str
    components: Path | None = None
    graph: Path | None = None
    trail: Path | None = None
    repo: Path | None = None
    prs: Path | None = None
    releases: Path | None = None
    meute: Path | None = None
    manual_review: Path | None = None
    execution_links: Path | None = None
    codeman_origin: str | None = None


@dataclass(frozen=True)
class SourceRow:
    label: str
    status: Literal["recorded", "missing", "invalid"]


@dataclass(frozen=True)
class ArchRow:
    ref: str
    relation: str
    state: str
    provenance: str
    target: str | None


@dataclass(frozen=True)
class FeatureRow:
    id: str
    title: str
    status: str
    state: str
    outcome: str | None
    tasks: tuple[str, ...]
    architecture: tuple[ArchRow, ...]


@dataclass(frozen=True)
class ComponentRow:
    id: str
    label: str
    kind: str
    paths: tuple[str, ...]
    parent: str | None
    provenance: str
    owner: str | None
    summary: str | None
    summary_provenance: str | None
    reviewed: bool


@dataclass(frozen=True)
class TaskRow:
    id: str
    title: str
    state: str
    evidence: ProgressEvidence


@dataclass(frozen=True)
class PlanningView:
    project: str
    features: tuple[FeatureRow, ...]
    components: tuple[ComponentRow, ...]
    tasks: tuple[TaskRow, ...]
    sources: tuple[SourceRow, ...]
    issues: tuple[Issue, ...]
    version: Literal[1] = 1
    meute: MeuteEvidence | None = None
    manual_review: ManualReview | None = None
    execution_links: ExecutionLinks | None = None


def _architecture_ref(ref: Ref) -> str:
    if ref.kind == "component":
        return str(ref)
    label = f"{ref.kind}:{planning_text(ref.id)}"
    return label if ref.fragment is None else f"{label}#{planning_text(ref.fragment)}"


def _load_component_model(
    inputs: PlanningInputs, sources: list[SourceRow], issues: list[Issue]
) -> ComponentModel | None:
    path = inputs.components or inputs.workspace / "components" / f"{inputs.project}.yaml"
    model = None
    label = "Component declarations"
    try:
        with open_directory(path.parent) as fd:
            entry_mode(path, fd)
            model, diagnostics = load_components(path, dir_fd=fd)
            issues.extend(diagnostics)
    except FileNotFoundError:
        if inputs.components is None:
            sources.append(SourceRow(label, "missing"))
            return None
        issues.append(Issue(path.name, "file", "configured component file is missing"))
    except (OSError, ValueError):
        issues.append(Issue(path.name, "file", "cannot open component file without symlinks"))
    if model and model.project != inputs.project:
        issues.append(Issue(path.name, "project", "expected the configured project"))
        model = None
    sources.append(SourceRow(label, "recorded" if model else "invalid"))
    return model


def _recorded[T](
    label: str,
    path: Path | None,
    load: Callable[[Path], T],
    sources: list[SourceRow],
    issues: list[Issue],
    *,
    fallback: T,
) -> T:
    if path is None:
        sources.append(SourceRow(label, "missing"))
        return fallback
    try:
        value = load(path)
    except TaskFileError as exc:
        sources.append(SourceRow(label, "invalid"))
        issues.append(Issue(exc.filename, exc.field_name, exc.message))
        return fallback
    sources.append(SourceRow(label, "recorded"))
    return value


def _scoped_intent(ws: Workspace, project: str) -> Workspace:
    features: dict[str, Feature] = {}
    for feature in ws.features:
        if feature.project == project:
            features.setdefault(feature.id, feature)
    return replace(ws, features=tuple(features.values()))


def _feature_row(
    ws: Workspace,
    feature: Feature,
    state: str,
    indexes: ArchitectureIndexes,
    model: ComponentModel | None,
) -> FeatureRow:
    trace = trace_feature(
        ws,
        indexes.graph,
        feature_ref(feature),
        trail=indexes.trail,
        components={model.project: model} if model is not None else None,
    )
    return FeatureRow(
        f"{feature.project}/{feature.id}",
        planning_text(feature.title),
        feature.status,
        state,
        planning_text(feature.outcome) if feature.outcome else None,
        tuple(
            dict.fromkeys(
                f"{ref.project}/{ref.id}" for ref in feature.tasks if ref.project == feature.project
            )
        ),
        tuple(
            ArchRow(
                _architecture_ref(link.ref),
                link.relation,
                link.state,
                link.provenance,
                f"{feature.project}/{link.ref.id}"
                if link.ref.kind == "component" and link.state == "existing"
                else None,
            )
            for link in trace.architecture
            if link.ref.project in (None, feature.project)
        ),
    )


def _component_rows(model: ComponentModel | None) -> tuple[ComponentRow, ...]:
    if model is None:
        return ()
    return tuple(
        ComponentRow(
            f"{model.project}/{row.id}",
            planning_text(row.label),
            planning_text(row.kind),
            tuple(map(planning_path, row.paths)),
            f"{model.project}/{row.parent}" if row.parent else None,
            "proposed" if row.kind == PROPOSAL_KIND else "declared",
            planning_text(row.owner) if row.owner else None,
            planning_text(row.summary.text) if row.summary else None,
            row.summary.provenance if row.summary else None,
            bool(row.summary and row.summary.reviewed_on),
        )
        for row in model.components
    )


def _public_rung(rung: Rung, *, generated: bool) -> Rung:
    if isinstance(rung, str):
        return rung
    if generated:
        return tuple(map(safe, rung))
    return tuple(planning_text(ref, prose=False) for ref in rung)


def _public_evidence(evidence: ProgressEvidence) -> ProgressEvidence:
    return ProgressEvidence(
        **{
            field.name: _public_rung(
                getattr(evidence, field.name), generated=field.name == "generated"
            )
            for field in fields(evidence)
        }
    )


def _public_meute(snapshot: MeuteEvidence | None) -> MeuteEvidence | None:
    if snapshot is None:
        return None
    reports = tuple(
        replace(report, task=None)
        if report.task is not None and report.task.partition("/")[0] != snapshot.project
        else report
        for report in snapshot.reports
    )
    return replace(snapshot, reports=reports)


def _load_supplemental(
    inputs: PlanningInputs, tasks: set[str], sources: list[SourceRow], issues: list[Issue]
) -> tuple[MeuteSnapshot | None, ManualReview | None]:
    meute = manual = None
    if (path := inputs.meute) is not None:
        load = partial(load_meute, project=inputs.project)
        meute = _recorded(MEUTE_SOURCE_LABEL, path, load, sources, issues, fallback=None)
    if (path := inputs.manual_review) is not None:
        read = partial(load_manual_review, project=inputs.project, tasks=tasks)
        manual = _recorded(MANUAL_REVIEW_LABEL, path, read, sources, issues, fallback=None)
    return meute, manual


def _load_execution_links(
    inputs: PlanningInputs,
    tasks: set[str],
    sources: list[SourceRow],
    issues: list[Issue],
) -> ExecutionLinks | None:
    origin = codeman_origin(inputs.codeman_origin)
    if inputs.execution_links is None:
        return None
    read = partial(load_execution_links, project=inputs.project, tasks=tasks, origin=origin)
    return _recorded(
        EXECUTION_LINKS_LABEL, inputs.execution_links, read, sources, issues, fallback=None
    )


def _load_indexes(
    inputs: PlanningInputs, sources: list[SourceRow], issues: list[Issue]
) -> ArchitectureIndexes:
    return ArchitectureIndexes(
        _recorded("Floorplan graph", inputs.graph, load_graph, sources, issues, fallback=None),
        _recorded("Trail wiring", inputs.trail, load_wiring, sources, issues, fallback=None),
    )


def _task_rows(report: ProgressReport, titles: dict[str, str]) -> tuple[TaskRow, ...]:
    return tuple(
        TaskRow(row.key, titles[row.key], row.state, _public_evidence(row.evidence))
        for row in report.tasks
        if row.key in titles
    )


def load_planning_view(inputs: PlanningInputs) -> PlanningView:
    project = inputs.project
    if len(project) > MAX_PROJECT_ID_LENGTH or not re.fullmatch(PROJECT_ID, project):
        raise TaskFileError(Path("serve"), "project", "expected a project identifier")
    shared: Counter[str] = Counter()
    ws = _scoped_intent(
        load_workspace(inputs.workspace, issue_filter=project_issue_filter(project, shared)),
        project,
    )
    sources: list[SourceRow] = []
    issues = [*ws.issues, *issue_summary(shared, ws.omitted_issues)]
    model = _load_component_model(inputs, sources, issues)
    titles = {
        f"{t.project}/{t.id}": planning_text(t.title) for t in ws.tasks if t.project == project
    }
    if not (model or ws.features or titles or any(p == project for p, _ in ws.milestones)):
        raise TaskFileError(Path("serve"), "project", "no records for the configured project")
    indexes = _load_indexes(inputs, sources, issues)
    prs = _recorded("Pull requests", inputs.prs, load_prs, sources, issues, fallback=())
    releases = _recorded("Releases", inputs.releases, load_releases, sources, issues, fallback=())
    known = frozenset(f"{t.project}/{t.id}" for t in ws.tasks)
    git = _recorded(
        "Local Git",
        inputs.repo,
        lambda path: load_git(path, prs, releases, known),
        sources,
        issues,
        fallback=EMPTY_GIT_EVIDENCE,
    )
    task_keys = set(titles)
    meute, manual = _load_supplemental(inputs, task_keys, sources, issues)
    artifacts = (GeneratedArtifact(manual.task, manual.ref),) if manual is not None else ()
    report = derive_progress(ws, git, prs, artifacts, None, indexes, meute=meute)
    features = tuple(
        _feature_row(ws, feature, row.state, indexes, model)
        for feature, row in zip(ws.features, report.features, strict=True)
    )
    execution = _load_execution_links(inputs, task_keys, sources, issues)
    return PlanningView(
        project,
        features,
        _component_rows(model),
        _task_rows(report, titles),
        tuple(sources),
        tuple(map(public_issue, issues)),
        meute=_public_meute(report.meute),
        manual_review=manual,
        execution_links=execution,
    )
