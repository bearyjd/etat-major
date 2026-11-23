"""Derive task and feature progress from local intent, Git and recorded evidence."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from etat_major.evidence_git import GitEvidence, load_git
from etat_major.evidence_records import (
    GeneratedArtifact,
    PullRequest,
    branch_task,
    load_prs,
    load_releases,
    resolve_task_keys,
)
from etat_major.floorplan import FloorplanIndex
from etat_major.meute import MeuteEvidence, MeuteSnapshot, load_meute, resolve_meute
from etat_major.planning import BoardColumn, BoardEvidence, derive_board_column
from etat_major.records import ArchitectureLink, Feature
from etat_major.taskfile import Task, TaskFileError
from etat_major.trace import _arch_state
from etat_major.trail import SymbolIndex
from etat_major.workspace import Issue, Workspace, WorkspaceError, linked_decisions, load_workspace

type Rung = tuple[str, ...] | Literal["unverified"]


def _rung(refs: Iterable[str]) -> Rung:
    return tuple(sorted(set(refs))) or "unverified"


@dataclass(frozen=True)
class ProgressEvidence:
    generated: Rung = "unverified"
    committed: Rung = "unverified"
    tested: Rung = "unverified"
    reviewed: Rung = "unverified"
    merged: Rung = "unverified"
    shipped: Rung = "unverified"
    accepted: Rung = "unverified"


@dataclass(frozen=True)
class TaskProgress:
    key: str
    state: BoardColumn
    evidence: ProgressEvidence
    merge_checks: tuple[str, ...]
    released_merges: tuple[str, ...]
    work_started: bool


@dataclass(frozen=True)
class FeatureProgress:
    key: str
    state: str
    tasks: tuple[str, ...]
    architecture: tuple[tuple[str, str], ...]
    acceptance: Rung


@dataclass(frozen=True)
class ProgressReport:
    tasks: tuple[TaskProgress, ...]
    features: tuple[FeatureProgress, ...]
    disconnected_commits: tuple[str, ...]
    disconnected_prs: tuple[int, ...]
    stale_milestones: tuple[str, ...]
    stale_links: tuple[tuple[str, str], ...]
    unimplemented_requirements: tuple[tuple[str, str], ...]
    issues: tuple[Issue, ...]
    omitted_issues: int
    version: Literal[1] = 1
    meute: MeuteEvidence | None = None


def _key(task: Task | Feature) -> str:
    return f"{task.project}/{task.id}"


def _acceptable(task: Task) -> bool:
    return task.status == "done" and bool(task.accepted_by and task.accepted_on)


def _pr_merge(pr: PullRequest) -> str | None:
    return pr.merge_commit.oid if pr.state == "MERGED" and pr.merge_commit else None


def _pr_keys(pr: PullRequest, git: GitEvidence, known: frozenset[str]) -> tuple[str, ...]:
    trailers = git.trailers.get(_pr_merge(pr) or "", ())
    trailers = trailers or git.trailers.get(pr.head_oid or "", ())
    return resolve_task_keys(trailers=trailers, branch=pr.head, body=pr.body, known=known)


def _check_refs(pr: PullRequest) -> tuple[list[str], bool]:
    refs = []
    passes_on_merge = False
    merge = _pr_merge(pr)
    for index, check in enumerate(pr.checks or (), start=1):
        oid = check.commit_oid or pr.head_oid
        if check.commit_oid is not None and oid not in {merge, pr.head_oid}:
            continue
        if not check.passed:
            return [], False
        refs.append(f"pr:{pr.number}/check:{index}")
        passes_on_merge |= merge is not None and oid == merge
    return refs, passes_on_merge


def _board_evidence(prs: list[PullRequest], *, branch: bool, merged: bool) -> BoardEvidence:
    return BoardEvidence(
        branch_open=branch,
        pr_open_draft=any(pr.state == "OPEN" and pr.is_draft for pr in prs),
        pr_open_ready=any(pr.state == "OPEN" and not pr.is_draft for pr in prs),
        pr_merged=merged,
    )


def _task_progress(
    task: Task,
    git: GitEvidence,
    commits: list[str],
    prs: list[PullRequest],
    dependencies: Mapping[str, str],
    branches: set[str],
    artifacts: list[str],
) -> TaskProgress:
    key = _key(task)
    merged = {f"commit:{oid}" for oid in commits if oid in git.default_commits}
    reviewed, tested, shipped = set(), set(), set()
    merge_checks, released_merges = set(), set()
    for pr in prs:
        ref = f"pr:{pr.number}"
        checks, merge_checked = _check_refs(pr)
        tested.update(checks)
        if pr.state != "CLOSED" and pr.review_decision == "APPROVED":
            reviewed.add(ref)
        if pr.state != "MERGED":
            continue
        merged.add(ref)
        if merge_checked:
            merge_checks.add(ref)
        if merge := _pr_merge(pr):
            merged.discard(f"commit:{merge}")
            if tags := git.releases.get(merge):
                shipped.update(f"tag:{tag}" for tag in tags)
                released_merges.add(ref)
    evidence = ProgressEvidence(
        generated=_rung(f"artifact:{ref}" for ref in artifacts),
        committed=_rung(f"commit:{oid}" for oid in commits),
        tested=_rung(tested),
        reviewed=_rung(reviewed),
        merged=_rung(merged),
        shipped=_rung(shipped),
        accepted=_rung((f"task:{key}",) if _acceptable(task) else ()),
    )
    board = _board_evidence(prs, branch=key in branches, merged=bool(merged))
    return TaskProgress(
        key,
        derive_board_column(task, dependencies, board),
        evidence,
        tuple(sorted(merge_checks)),
        tuple(sorted(released_merges)),
        bool(commits or merged or board.branch_open or board.pr_open_draft or board.pr_open_ready),
    )


def _feature_state(
    ws: Workspace,
    feature: Feature,
    linked: list[TaskProgress],
    *,
    all_found: bool,
) -> str:
    decisions = {d.status for d in linked_decisions(ws, feature)}
    exits = decisions & {"rejected", "postponed"}
    if "approved" not in decisions and len(exits) == 1:
        return next(iter(exits))
    if (
        all_found
        and feature.accepted_by
        and feature.accepted_on
        and all(
            task.evidence.accepted != "unverified"
            and task.merge_checks
            and set(task.merge_checks)
            == {ref for ref in task.evidence.merged if ref.startswith("pr:")}
            for task in linked
        )
    ):
        if all(task.released_merges == task.merge_checks for task in linked):
            return "released"
        return "verified"
    needs_acceptance = not all_found or any(
        task.evidence.accepted == "unverified" for task in linked
    )
    if needs_acceptance and any(task.work_started for task in linked):
        return "implementing"
    if "approved" in decisions and feature.status != "planned":
        return "approved"
    return feature.status


@dataclass(frozen=True)
class ArchitectureIndexes:
    graph: FloorplanIndex | None = None
    trail: SymbolIndex | None = None


_EMPTY_ARCHITECTURE_INDEXES = ArchitectureIndexes()


def _architecture(
    link: ArchitectureLink,
    git: GitEvidence,
    indexes: ArchitectureIndexes,
    ordinal: int,
) -> tuple[str, str]:
    ref = link.ref
    label = str(ref)
    if any(char in ref.id or char in (ref.fragment or "") for char in ":\\"):
        label = f"architecture:{ordinal}"
    if ref.kind == "fp:f" and indexes.graph is None and git.files is not None:
        present = ref.id in git.files
        if link.relation == "new":
            return label, "built" if present else "gap"
        return label, "existing" if present else "stale"
    return label, _arch_state(link, indexes.graph, None, indexes.trail)


def _feature_progress(
    ws: Workspace,
    feature: Feature,
    tasks: Mapping[str, TaskProgress],
    git: GitEvidence,
    indexes: ArchitectureIndexes,
) -> FeatureProgress:
    keys = tuple(dict.fromkeys(f"{ref.project}/{ref.id}" for ref in feature.tasks))
    linked = [tasks[k] for k in keys if k in tasks]
    key = _key(feature)
    return FeatureProgress(
        key,
        _feature_state(ws, feature, linked, all_found=bool(keys) and len(keys) == len(linked)),
        keys,
        tuple(
            _architecture(link, git, indexes, i) for i, link in enumerate(feature.architecture, 1)
        ),
        _rung((f"feature:{key}",) if feature.accepted_by and feature.accepted_on else ()),
    )


def _stale_milestones(
    ws: Workspace,
    features: tuple[FeatureProgress, ...],
    tasks: Mapping[str, TaskProgress],
    today: date | None,
) -> tuple[str, ...]:
    if today is None:
        return ()
    states: dict[str, list[bool]] = defaultdict(list)
    for task in ws.tasks:
        if task.milestone:
            states[f"milestone:{task.project}/{task.milestone}"].append(
                tasks[_key(task)].state == "done"
            )
    for feature, progress in zip(ws.features, features, strict=True):
        for milestone in feature.milestones:
            states[str(milestone)].append(progress.state in {"verified", "released"})
    stale = set()
    for project, milestone in ws.milestones:
        ref = f"milestone:{project}/{milestone.id}"
        complete = states[ref] and all(states[ref])
        if milestone.target_date and milestone.target_date < today and not complete:
            stale.add(ref)
    return tuple(sorted(stale))


def _link_work(
    git: GitEvidence,
    prs: tuple[PullRequest, ...],
    known: frozenset[str],
) -> tuple[dict[str, list[str]], dict[str, list[PullRequest]], list[str], list[int]]:
    commit_keys = dict(git.commits)
    linked_prs: dict[str, list[PullRequest]] = defaultdict(list)
    disconnected_prs = []
    for pr in prs:
        keys = _pr_keys(pr, git, known)
        if not keys:
            disconnected_prs.append(pr.number)
            continue
        for key in keys:
            linked_prs[key].append(pr)
        for oid in (pr.head_oid, _pr_merge(pr)):
            if oid in commit_keys and not git.commits[oid]:
                commit_keys[oid] = tuple(dict.fromkeys((*commit_keys[oid], *keys)))
    linked_commits: dict[str, list[str]] = defaultdict(list)
    disconnected_commits = []
    for oid, keys in commit_keys.items():
        if not keys:
            disconnected_commits.append(oid)
        for key in keys:
            linked_commits[key].append(oid)
    return linked_commits, linked_prs, disconnected_commits, disconnected_prs


def _architecture_problems(
    features: tuple[FeatureProgress, ...],
    problem: str,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (f"feature:{feature.key}", ref)
                for feature in features
                for ref, state in feature.architecture
                if state == problem
            }
        )
    )


def derive_progress(
    ws: Workspace,
    git: GitEvidence,
    prs: tuple[PullRequest, ...],
    artifacts: tuple[GeneratedArtifact, ...],
    today: date | None,
    indexes: ArchitectureIndexes,
    *,
    meute: MeuteSnapshot | None = None,
) -> ProgressReport:
    """Resolve evidence against validated intent and optional recorded inputs."""
    known = frozenset(map(_key, ws.tasks))
    commits, linked_prs, disconnected_commits, disconnected_prs = _link_work(git, prs, known)
    branches = {key for name in git.heads if (key := branch_task(name, known))}
    dependencies: dict[str, dict[str, str]] = defaultdict(dict)
    linked_artifacts: dict[str, list[str]] = defaultdict(list)
    for task in ws.tasks:
        dependencies[task.project][task.id] = (
            "ready" if task.status == "done" and not _acceptable(task) else task.status
        )
    recorded = resolve_meute(meute, known) if meute is not None else None
    for artifact in (*artifacts, *(recorded.artifacts() if recorded else ())):
        linked_artifacts[artifact.task].append(artifact.ref)
    task_rows = {
        key: _task_progress(
            task,
            git,
            commits[key],
            linked_prs[key],
            dependencies[task.project],
            branches,
            linked_artifacts[key],
        )
        for task in ws.tasks
        for key in (_key(task),)
    }
    feature_rows = tuple(_feature_progress(ws, f, task_rows, git, indexes) for f in ws.features)
    stale = _architecture_problems(feature_rows, "stale")
    gaps = _architecture_problems(feature_rows, "gap")
    return ProgressReport(
        tuple(task_rows[k] for k in sorted(task_rows)),
        feature_rows,
        tuple(sorted(disconnected_commits)),
        tuple(sorted(disconnected_prs)),
        _stale_milestones(ws, feature_rows, task_rows, today),
        stale,
        gaps,
        ws.issues,
        ws.omitted_issues,
        meute=recorded,
    )


def load_progress(
    workspace: Path,
    repo: Path,
    prs: Path,
    releases: Path,
    *,
    artifacts: tuple[GeneratedArtifact, ...] = (),
    today: date | None = None,
    use_clock: bool = True,
    indexes: ArchitectureIndexes = _EMPTY_ARCHITECTURE_INDEXES,
    meute: Path | None = None,
) -> ProgressReport:
    try:
        intent = load_workspace(workspace)
    except WorkspaceError:
        raise TaskFileError(workspace, "workspace", "cannot open intent workspace") from None
    pull_requests = load_prs(prs)
    git = load_git(repo, pull_requests, load_releases(releases), frozenset(map(_key, intent.tasks)))
    if today is None and use_clock:
        today = datetime.now(UTC).date()
    snapshot = load_meute(meute) if meute is not None else None
    return derive_progress(intent, git, pull_requests, artifacts, today, indexes, meute=snapshot)
