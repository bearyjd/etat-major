"""Build a sanitized, project-scoped snapshot from local intent and recorded evidence."""

import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Literal
from unicodedata import normalize

from etat_major.component_paths import component_file_path
from etat_major.components import MAX_PROJECT_ID_LENGTH, ComponentModel, load_components
from etat_major.components_seed import PROPOSAL_KIND
from etat_major.evidence import ArchitectureIndexes, ProgressEvidence, Rung, derive_progress
from etat_major.evidence_git import EMPTY_GIT_EVIDENCE, load_git
from etat_major.evidence_records import load_prs, load_releases
from etat_major.floorplan import load_graph
from etat_major.localfiles import entry_mode, open_directory
from etat_major.records import Feature
from etat_major.refs import PROJECT_ID, Ref, RefError, parse_ref
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import public_text, safe
from etat_major.trace import trace_feature
from etat_major.trail import load_wiring
from etat_major.workspace import Issue, Workspace, feature_ref, load_workspace

_PATH_PUNCTUATION = str.maketrans("%#", "__")


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


def _text(value: str, *, limit: int = 512, prose: bool = True) -> str:
    return safe(public_text(value, scp_remotes=prose), limit=limit)


def _architecture_ref(ref: Ref) -> str:
    if ref.kind == "component":
        return str(ref)
    label = f"{ref.kind}:{_text(ref.id)}"
    return label if ref.fragment is None else f"{label}#{_text(ref.fragment)}"


def _path_text(value: str) -> str:
    try:
        component_file_path(normalize("NFKC", value).translate(_PATH_PUNCTUATION))
    except ValueError:
        return "[redacted location]"
    return safe(value, limit=256)


def _issue_path(value: str) -> str:
    if value.startswith(("feature:", "task:", "milestone:")):
        try:
            parse_ref(value)
        except RefError:
            pass
        else:
            return safe(value, limit=256)
    return _path_text(value)


def _issue(issue: Issue) -> Issue:
    return replace(
        issue,
        path=_issue_path(issue.path),
        field=_text(issue.field or "file", limit=80),
        message=_text(issue.message),
    )


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


def _project_issue_filter(project: str, shared: Counter[str]) -> Callable[[Issue], bool]:
    sections = ("features", "tasks", "milestones")
    folders = tuple(f"{section}/{project}" for section in sections)
    exact_paths = frozenset((*sections, *folders))
    prefixes = (
        *(f"{kind}:{project}/" for kind in ("feature", "task", "milestone")),
        *(folder + "/" for folder in folders),
    )

    def accept(issue: Issue) -> bool:
        for section, ref_prefix in (("decisions", "decision:"), ("research", "research:")):
            if issue.path == section or issue.path.startswith((section + "/", ref_prefix)):
                shared[section] += 1
                return False
        return issue.path in exact_paths or issue.path.startswith(prefixes)

    return accept


def _shared_issue_rows(shared: Counter[str]) -> Iterator[Issue]:
    for section, count in sorted(shared.items()):
        noun = "diagnostic" if count == 1 else "diagnostics"
        yield Issue(section, "records", f"{count} {noun} in shared {section}")


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
        _text(feature.title),
        feature.status,
        state,
        _text(feature.outcome) if feature.outcome else None,
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
            _text(row.label),
            _text(row.kind),
            tuple(map(_path_text, row.paths)),
            f"{model.project}/{row.parent}" if row.parent else None,
            "proposed" if row.kind == PROPOSAL_KIND else "declared",
            _text(row.owner) if row.owner else None,
            _text(row.summary.text) if row.summary else None,
            row.summary.provenance if row.summary else None,
            bool(row.summary and row.summary.reviewed_on),
        )
        for row in model.components
    )


def _public_rung(rung: Rung) -> Rung:
    return rung if isinstance(rung, str) else tuple(_text(ref, prose=False) for ref in rung)


def _public_evidence(evidence: ProgressEvidence) -> ProgressEvidence:
    return ProgressEvidence(
        **{field.name: _public_rung(getattr(evidence, field.name)) for field in fields(evidence)}
    )


def load_planning_view(inputs: PlanningInputs) -> PlanningView:
    project = inputs.project
    if len(project) > MAX_PROJECT_ID_LENGTH or not re.fullmatch(PROJECT_ID, project):
        raise TaskFileError(Path("serve"), "project", "expected a project identifier")
    shared: Counter[str] = Counter()
    ws = _scoped_intent(
        load_workspace(inputs.workspace, issue_filter=_project_issue_filter(project, shared)),
        project,
    )
    sources: list[SourceRow] = []
    issues = [*ws.issues, *_shared_issue_rows(shared)]
    if ws.omitted_issues:
        issues.append(Issue("workspace", "records", f"{ws.omitted_issues} more project issues"))
    model = _load_component_model(inputs, sources, issues)
    titles = {f"{t.project}/{t.id}": _text(t.title) for t in ws.tasks if t.project == project}
    if not (model or ws.features or titles or any(p == project for p, _ in ws.milestones)):
        raise TaskFileError(Path("serve"), "project", "no records for the configured project")
    indexes = ArchitectureIndexes(
        _recorded("Floorplan graph", inputs.graph, load_graph, sources, issues, fallback=None),
        _recorded("Trail wiring", inputs.trail, load_wiring, sources, issues, fallback=None),
    )
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
    report = derive_progress(ws, git, prs, (), None, indexes)
    features = tuple(
        _feature_row(ws, feature, row.state, indexes, model)
        for feature, row in zip(ws.features, report.features, strict=True)
    )
    tasks = tuple(
        TaskRow(row.key, titles[row.key], row.state, _public_evidence(row.evidence))
        for row in report.tasks
        if row.key in titles
    )
    return PlanningView(
        project, features, _component_rows(model), tasks, tuple(sources), tuple(map(_issue, issues))
    )
