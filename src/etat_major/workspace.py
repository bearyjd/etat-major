"""Load an intent workspace (``research/``, ``decisions/``, ``features/<project>/``).

Every file and cross-file problem is collected as an ``Issue``; loading never stops at the
first error and unresolved references are reported as ``missing`` rather than raised.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from etat_major.records import (
    Decision,
    Feature,
    ResearchArtifact,
    load_decision,
    load_feature,
    load_research,
)
from etat_major.refs import Ref
from etat_major.taskfile import TaskFileError


@dataclass(frozen=True)
class Issue:
    """A problem in a file (``path`` is workspace-relative) or in a record (``path`` is its ref)."""

    path: str
    field: str | None
    message: str

    def __str__(self) -> str:
        where = f"{self.path}: field '{self.field}'" if self.field else self.path
        return f"{where}: {self.message}"


@dataclass(frozen=True)
class Workspace:
    research: tuple[ResearchArtifact, ...]
    decisions: tuple[Decision, ...]
    features: tuple[Feature, ...]
    issues: tuple[Issue, ...]

    def get_research(self, record_id: str) -> ResearchArtifact | None:
        return next((r for r in self.research if r.id == record_id), None)

    def get_decision(self, record_id: str) -> Decision | None:
        return next((d for d in self.decisions if d.id == record_id), None)

    def get_feature(self, project: str, record_id: str) -> Feature | None:
        return next((f for f in self.features if (f.project, f.id) == (project, record_id)), None)

    def get_feature_by_ref(self, ref: Ref) -> Feature | None:
        return self.get_feature(ref.project or "", ref.id)


def feature_ref(feature: Feature) -> Ref:
    return Ref("feature", feature.id, project=feature.project)


def linked_decisions(ws: Workspace, feature: Feature) -> tuple[Decision, ...]:
    """Decisions the feature lists, plus decisions that list the feature."""
    me = feature_ref(feature)
    listed = {d.id for d in feature.decisions}
    return tuple(d for d in ws.decisions if d.id in listed or me in d.features)


def _load_dir[T](
    root: Path, sub: str, loader: Callable[[Path], T], issues: list[Issue]
) -> list[tuple[Path, T]]:
    out: list[tuple[Path, T]] = []
    for path in sorted((root / sub).glob("*.md")) if (root / sub).is_dir() else []:
        try:
            out.append((path, loader(path)))
        except TaskFileError as exc:
            issues.append(Issue(path.relative_to(root).as_posix(), exc.field, _message(exc)))
    return out


def _message(exc: TaskFileError) -> str:
    prefix = f"{exc.path.name}: field '{exc.field}': " if exc.field else f"{exc.path.name}: "
    return str(exc).removeprefix(prefix)


def _load_features(root: Path, issues: list[Issue]) -> list[Feature]:
    features: list[Feature] = []
    base = root / "features"
    for pdir in sorted(base.iterdir()) if base.is_dir() else []:
        if not pdir.is_dir():
            continue
        for path, feature in _load_dir(root, f"features/{pdir.name}", load_feature, issues):
            if feature.project != pdir.name:
                rel = path.relative_to(root).as_posix()
                msg = f"project '{feature.project}' does not match directory '{pdir.name}'"
                issues.append(Issue(rel, "project", msg))
            else:
                features.append(feature)
    return features


def _duplicates(records: list[Ref], issues: list[Issue]) -> None:
    for ref, n in sorted(Counter(records).items(), key=lambda kv: str(kv[0])):
        if n > 1:
            issues.append(Issue(str(ref), "id", f"duplicate id: {n} records share {ref}"))


def _missing(owner: Ref, field: str, ref: Ref) -> Issue:
    return Issue(str(owner), field, f"missing: {ref} does not resolve to a record")


def _check_decision(ws: Workspace, d: Decision) -> list[Issue]:
    owner, out = Ref("decision", d.id), []
    for ref in d.evidence:
        found = ws.get_research(ref.id)
        if found is None or (ref.fragment and ref.fragment not in {f.id for f in found.findings}):
            out.append(_missing(owner, "evidence", ref))
    out += [
        _missing(owner, "features", ref) for ref in d.features if not ws.get_feature_by_ref(ref)
    ]
    return out


def _check_feature(ws: Workspace, f: Feature) -> list[Issue]:
    owner = feature_ref(f)
    out = [_missing(owner, "research", r) for r in f.research if not ws.get_research(r.id)]
    out += [_missing(owner, "decisions", d) for d in f.decisions if not ws.get_decision(d.id)]
    if f.status == "planned" and not any(d.status == "approved" for d in linked_decisions(ws, f)):
        out.append(
            Issue(
                str(owner),
                "status",
                "status 'planned' requires a linked Decision with status approved",
            )
        )
    return out


def _cross_validate(ws: Workspace) -> list[Issue]:
    issues: list[Issue] = []
    _duplicates([Ref("research", r.id) for r in ws.research], issues)
    _duplicates([Ref("decision", d.id) for d in ws.decisions], issues)
    _duplicates([feature_ref(f) for f in ws.features], issues)
    for d in ws.decisions:
        issues += _check_decision(ws, d)
    for f in ws.features:
        issues += _check_feature(ws, f)
    return issues


def load_workspace(root: Path) -> Workspace:
    issues: list[Issue] = []
    research = [r for _, r in _load_dir(root, "research", load_research, issues)]
    decisions = [d for _, d in _load_dir(root, "decisions", load_decision, issues)]
    ws = Workspace(tuple(research), tuple(decisions), tuple(_load_features(root, issues)), ())
    return Workspace(ws.research, ws.decisions, ws.features, tuple(issues + _cross_validate(ws)))
