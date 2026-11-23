"""CLI commands for the workspace component model and seed proposals."""

import argparse
import sys
from collections.abc import Iterable, Iterator
from dataclasses import replace
from pathlib import Path
from unicodedata import normalize

from etat_major.cli_json import json_result
from etat_major.component_paths import component_file_path
from etat_major.components import ComponentModel, Coverage, load_component_workspace
from etat_major.components_seed import seed_components
from etat_major.floorplan import load_graph
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import is_control, public_text, safe
from etat_major.workspace import Issue

_NONMATCHING_PUNCTUATION = str.maketrans("%#", "__")


def components_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    validate = actions.add_parser("validate", help="check all workspace component files")
    mapping = actions.add_parser("map", help="find the owner of a repository-relative path")
    coverage = actions.add_parser("coverage", help="measure ownership of recorded Floorplan files")
    seed = actions.add_parser("seed", help="propose components from recorded module evidence")
    for action in (validate, mapping, coverage):
        action.add_argument("--workspace", type=Path, required=True)
    for action in (mapping, coverage, seed):
        action.add_argument("--project", required=True)
    mapping.add_argument("--path", required=True)
    coverage.add_argument("--graph", type=Path, required=True)
    seed.add_argument("--root", type=Path, required=True)
    seed.add_argument("--trail", type=Path)
    output = seed.add_mutually_exclusive_group(required=True)
    output.add_argument("--out", type=Path, help="new component YAML file")
    output.add_argument("--proposal-for", type=Path, help="existing model to propose additions for")
    for action in (validate, mapping, coverage, seed):
        action.add_argument("--format", choices=("text", "json"), default="text")


def _display(text: str) -> str:
    return safe(public_text(text))


def _result(
    args: argparse.Namespace,
    data: dict[str, object] | None,
    issues: tuple[Issue, ...],
    lines: Iterable[str] = (),
) -> int:
    status = 2 if data is None else int(any(issue.blocking for issue in issues))
    if args.format == "json":
        escaped = tuple(
            replace(
                issue,
                path=_display(issue.path),
                field=_display(issue.field or "file"),
                message=_display(issue.message),
                severity="error" if issue.blocking else "warning",
            )
            for issue in issues
        )
        return json_result(f"components-{args.action}", status, data, issues=escaped)
    for issue in issues:
        print(f"{issue.severity}: {_display(str(issue))}", file=sys.stderr)
    for line in lines:
        print(safe(line))
    return status


def _checked_path(path: str, origin: Path, field: str) -> str:
    try:
        return component_file_path(path)
    except ValueError:
        raise TaskFileError(
            origin, field, "expected a safe repository-relative file path"
        ) from None


def _tie_issue(project: str, path: str, ties: tuple[str, ...]) -> Issue:
    return Issue(
        f"components/{project}.yaml",
        "paths",
        f"ownership tie for {path}: {', '.join(ties)}",
        severity="warning",
        blocking=False,
    )


def _map(args: argparse.Namespace, model: ComponentModel, issues: tuple[Issue, ...]) -> int:
    path = _checked_path(args.path, Path("components-map"), "path")
    match = model.owner_of(path)
    component = match.component
    ancestors: list[str] = []
    if component is not None:
        ancestors = [parent.id for parent in model.ancestors_of(component.id)]
    if match.ties:
        issues += (_tie_issue(model.project, path, match.ties),)
    data = {
        "project": model.project,
        "path": safe(path),
        "component": component.id if component else None,
        "ancestors": ancestors,
        "ties": list(match.ties),
    }
    lines = [f"{path}  {component.id if component else 'unowned'}"]
    if ancestors:
        lines.append(f"Parents  {' -> '.join(ancestors)}")
    return _result(args, data, issues, lines)


def _coverage_label(path: str, ordinal: int) -> str:
    try:
        component_file_path(normalize("NFKC", path).translate(_NONMATCHING_PUNCTUATION))
    except ValueError:
        # The colon in the first segment cannot collide with any accepted Floorplan path.
        return f"[redacted path:{ordinal}]"
    return safe(path)


def _coverage(args: argparse.Namespace, model: ComponentModel, issues: tuple[Issue, ...]) -> int:
    paths = load_graph(args.graph).file_paths
    matchable, unsupported = [], []
    for path in paths:
        if any(map(is_control, path)):
            raise TaskFileError(
                args.graph, "files", "expected a safe repository-relative file path"
            )
        try:
            matchable.append(component_file_path(path))
        except ValueError:
            unsupported.append(path)
    report = model.coverage(matchable)
    if unsupported:
        count = len(unsupported)
        issues += (
            Issue(
                args.graph.name,
                "files",
                f"{count} recorded paths cannot be matched by component declarations",
                "warning",
                False,
            ),
        )
        report = replace(
            report,
            unowned=tuple(sorted((*report.unowned, *unsupported))),
            percentage=100 * len(report.owned) / len(paths),
        )
    labels = {path: _coverage_label(path, ordinal) for ordinal, path in enumerate(sorted(paths), 1)}
    report = replace(
        report,
        owned=tuple(sorted(labels[path] for path in report.owned)),
        unowned=tuple(sorted(labels[path] for path in report.unowned)),
        ties=tuple((labels[path], owners) for path, owners in report.ties),
    )
    positions = {path: index for index, path in enumerate(report.unowned, 1)}
    issues += tuple(
        _tie_issue(model.project, f"unowned path {positions[path]}", owners)
        for path, owners in report.ties
    )
    data = {
        "project": model.project,
        "owned": list(report.owned),
        "unowned": list(report.unowned),
        "percentage": report.percentage,
    }
    return _result(args, data, issues, _coverage_lines(report))


def _coverage_lines(report: Coverage) -> Iterator[str]:
    yield f"{report.percentage:.2f}% owned"
    yield from (f"owned  {path}" for path in report.owned)
    yield from (f"unowned  {path}" for path in report.unowned)


def _seed(args: argparse.Namespace) -> int:
    result = seed_components(
        args.root, args.project, trail=args.trail, out=args.out, proposal_for=args.proposal_for
    )
    output = _display(result.output)
    data = {
        "project": result.project,
        "output": output,
        "components": list(result.components),
    }
    line = f"Wrote {output} with {len(result.components)} proposed components"
    return _result(args, data, result.issues, (line,))


def run_components(args: argparse.Namespace) -> int:
    if args.action == "seed":
        return _seed(args)
    models, issues = load_component_workspace(args.workspace)
    if args.action == "validate":
        return _result(args, {}, issues, () if any(issue.blocking for issue in issues) else ("ok",))
    model = models.get(args.project)
    if model is None:
        project_file = f"components/{args.project}.yaml"
        matching = tuple(issue for issue in issues if issue.path in {project_file, "components"})
        return _result(
            args,
            None,
            matching or (Issue("components", "project", "no component model for this project"),),
        )
    if args.action == "map":
        return _map(args, model, issues)
    return _coverage(args, model, issues)
