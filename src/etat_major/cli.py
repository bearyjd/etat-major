"""``etat-major`` command line. All commands operate locally.

Exit codes: 0 ok; 1 the trace has missing/stale/gap items or the workspace has validation
errors; 2 usage errors (bad arguments, unreadable workspace or graph file).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from etat_major.cli_json import (
    COMMAND_NAMES,
    decisions_data,
    json_error,
    json_format_requested,
    json_result,
    trace_data,
    trace_issues,
)
from etat_major.evidence import ArchitectureIndexes, load_progress
from etat_major.evidence_render import progress_data, render_text
from etat_major.floorplan import load_graph
from etat_major.refs import RefError, parse_ref
from etat_major.render import render_trace
from etat_major.repo_index import load_repo_index
from etat_major.research_brief import write_brief
from etat_major.research_import import import_answer
from etat_major.taskfile import TaskFileError
from etat_major.text_safety import public_text, safe
from etat_major.trace import TraceError, trace_feature
from etat_major.trail import load_wiring
from etat_major.workspace import Issue, load_workspace

OK, PROBLEMS, USAGE = 0, 1, 2
_ISSUE_PATH_LIMIT = 256
_INVALID_LINE_LIMIT = 512


EXIT_CODES = (
    "Exit codes\n"
    "0 success, including warnings and unsourced findings\n"
    "1 missing, stale or gap trace items, or workspace validation issues\n"
    "2 usage errors, including unknown features and invalid workspaces or graphs"
)


class _ArgumentError(ValueError):
    def __init__(self, parser: _ArgumentParser, message: str) -> None:
        super().__init__(message)
        self.parser = parser


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError(self, message)

    def text_error(self, message: str) -> None:
        detail = public_text(message)
        detail = detail if len(detail) <= 80 else detail[:80] + "…"
        super().error(safe(detail))


def _parser() -> argparse.ArgumentParser:
    help_options = {"epilog": EXIT_CODES, "formatter_class": argparse.RawDescriptionHelpFormatter}
    parser = _ArgumentParser(prog="etat-major", **help_options)
    sub = parser.add_subparsers(dest="command", required=True)
    trace = sub.add_parser(
        "trace", help="print the research-to-code trace of a feature", **help_options
    )
    trace.add_argument("ref", help="feature:<project>/<id>")
    trace.add_argument("--workspace", type=Path, required=True, help="intent workspace directory")
    trace.add_argument("--graph", type=Path, help="Floorplan graph.json (floorplan/graph@1)")
    trace.add_argument("--trail", type=Path, help="Trail wiring.json (version 1)")
    index = sub.add_parser(
        "index", help="export an architecture and symbol snapshot", **help_options
    )
    index.add_argument("--graph", type=Path, required=True, help="Floorplan graph.json")
    index.add_argument("--trail", type=Path, required=True, help="Trail wiring.json")
    index.add_argument("--revision", help="caller-supplied Git commit SHA for both artifacts")
    index.add_argument("--indexed-at", help="caller-supplied RFC 3339 index timestamp")
    decisions = sub.add_parser("decisions", help="decision records")
    dsub = decisions.add_subparsers(dest="action", required=True)
    dlist = dsub.add_parser(
        "list", help="list all decisions, rejected and postponed included", **help_options
    )
    dlist.add_argument("--workspace", type=Path, required=True)
    _research_parser(sub.add_parser("research", help="prepare and import manual research"))
    progress = sub.add_parser("progress", help="derive progress from local Git and recorded PRs")
    for flag in ("workspace", "repo", "prs", "releases"):
        progress.add_argument(f"--{flag}", type=Path, required=True)
    progress.add_argument("--graph", type=Path, help="optional recorded Floorplan graph")
    progress.add_argument("--trail", type=Path, help="optional recorded Trail wiring")
    progress.add_argument("--as-of", help="date for overdue milestone checks (YYYY-MM-DD)")
    workspace = sub.add_parser("workspace", help="inspect an intent workspace")
    validate = workspace.add_subparsers(dest="action", required=True).add_parser(
        "validate", help="report workspace validation issues", **help_options
    )
    validate.add_argument("--workspace", type=Path, required=True)
    for command in (trace, index, dlist, progress, validate):
        command.add_argument("--format", choices=("json", "text"), default="text")
    return parser


def _research_parser(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    brief = actions.add_parser("brief", help="write a research prompt for a feature")
    brief.add_argument("ref", help="feature:<project>/<id>")
    brief.add_argument("--workspace", type=Path, required=True)
    brief.add_argument("--out", type=Path, required=True)
    paste = actions.add_parser("import", help="save a pasted answer as an unreviewed artifact")
    paste.add_argument("file", type=Path)
    paste.add_argument("--workspace", type=Path, required=True)
    paste.add_argument("--id", required=True, help="four-digit research ID")


def _err(message: str) -> None:
    print(f"error: {safe(public_text(message))}", file=sys.stderr)


def _print_issues(issues: tuple[Issue, ...], omitted: int, *, generic: bool = False) -> None:
    for issue in issues:
        path = safe(issue.path, limit=_ISSUE_PATH_LIMIT)
        field = issue.field or "file"
        message = "invalid workspace record" if generic else public_text(issue.message)
        line = f"invalid: {path}: field '{field}': {message}"
        print(safe(line, limit=_INVALID_LINE_LIMIT), file=sys.stderr)
    if omitted:
        print(f"... {omitted} more issues", file=sys.stderr)


def _print_warnings(warnings: tuple[Issue, ...]) -> None:
    for warning in warnings:
        print(f"warning: {safe(public_text(str(warning)))}", file=sys.stderr)


def _load_indexes(args: argparse.Namespace) -> ArchitectureIndexes:
    return ArchitectureIndexes(
        load_graph(args.graph) if args.graph is not None else None,
        load_wiring(args.trail) if args.trail is not None else None,
    )


def _trace(args: argparse.Namespace) -> int:
    try:
        ref = parse_ref(args.ref)
    except RefError as exc:
        raise TaskFileError(Path("trace"), "ref", str(exc)) from None
    if ref.kind != "feature":
        raise TaskFileError(Path("trace"), "ref", "expected a feature reference")
    indexes = _load_indexes(args)
    ws = load_workspace(args.workspace)
    try:
        trace = trace_feature(ws, indexes.graph, ref, trail=indexes.trail)
    except TraceError as exc:
        raise TaskFileError(Path("trace"), "ref", str(exc)) from None
    status = PROBLEMS if trace.has_problems or ws.issues else OK
    if args.format == "json":
        warnings = tuple(Issue(str(ref), "evidence", message) for message in trace.warnings)
        return json_result(
            args.command,
            status,
            trace_data(trace, ws.omitted_issues),
            issues=ws.issues + trace_issues(trace),
            warnings=warnings,
        )
    _print_issues(ws.issues, ws.omitted_issues)
    sys.stdout.write(render_trace(trace))
    return status


def _decisions_list(args: argparse.Namespace) -> int:
    ws = load_workspace(args.workspace)
    decisions = sorted(ws.decisions, key=lambda decision: decision.id)
    status = PROBLEMS if ws.issues else OK
    if args.format == "json":
        return json_result(
            args.command,
            status,
            decisions_data(decisions, ws.omitted_issues),
            issues=ws.issues,
            warnings=ws.warnings,
        )
    _print_issues(ws.issues, ws.omitted_issues)
    _print_warnings(ws.warnings)
    for decision in decisions:
        by = decision.decided_by or "none"
        question = public_text(decision.question)
        print(safe(f"decision:{decision.id}  {decision.status}  {by}  {question}"))
    return status


def _workspace_validate(args: argparse.Namespace) -> int:
    ws = load_workspace(args.workspace, validate_all=True)
    status = PROBLEMS if ws.issues else OK
    if args.format == "json":
        return json_result(args.command, status, {}, issues=ws.issues, warnings=ws.warnings)
    _print_issues(ws.issues, ws.omitted_issues)
    _print_warnings(ws.warnings)
    return status


def _index(args: argparse.Namespace) -> int:
    index = load_repo_index(
        args.graph, args.trail, revision=args.revision, indexed_at=args.indexed_at
    )
    if args.format == "json":
        return json_result(args.command, OK, index.to_data())
    sys.stdout.write(index.to_text())
    return OK


def _research(args: argparse.Namespace) -> int:
    try:
        if args.action == "brief":
            write_brief(args.ref, args.workspace, args.out)
        else:
            import_answer(args.file, args.workspace, args.id)
    except TaskFileError as exc:
        _err(str(exc))
        return USAGE
    return OK


def _as_of(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise TaskFileError(Path("progress"), "as-of", "expected a YYYY-MM-DD date")


def _progress(args: argparse.Namespace) -> int:
    as_of = _as_of(args.as_of)
    report = load_progress(
        args.workspace,
        args.repo,
        args.prs,
        args.releases,
        indexes=_load_indexes(args),
        today=as_of,
        use_clock=args.format != "json",
    )
    status = PROBLEMS if report.issues else OK
    if args.format == "json":
        data = progress_data(report) | {
            "as_of": args.as_of,
            "omitted_issues": report.omitted_issues,
        }
        return json_result(args.command, status, data, issues=report.issues)
    _print_issues(report.issues, report.omitted_issues, generic=True)
    sys.stdout.write(render_text(report))
    return status


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        args = _parser().parse_args(argv)
    except _ArgumentError as exc:
        if argv and argv[0] in COMMAND_NAMES and json_format_requested(argv):
            issue = Issue(COMMAND_NAMES[argv[0]], "arguments", "invalid command arguments")
            return json_result(argv[0], USAGE, issues=(issue,))
        exc.parser.text_error(str(exc))
        return USAGE
    handlers = {
        "trace": _trace,
        "decisions": _decisions_list,
        "index": _index,
        "research": _research,
        "progress": _progress,
        "workspace": _workspace_validate,
    }
    try:
        return handlers[args.command](args)
    except TaskFileError as exc:
        if args.format == "json":
            return json_error(args.command, exc)
        _err(str(exc))
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
