"""``etat-major`` command line. Read-only: no network, no model calls, nothing written.

Exit codes: 0 ok; 1 the trace has missing/stale/gap items or the workspace has validation
errors; 2 usage errors (bad arguments, unreadable workspace or graph file).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from etat_major.floorplan import FloorplanError, load_graph
from etat_major.refs import RefError, parse_ref
from etat_major.render import render_trace
from etat_major.text_safety import bounded_repr, safe
from etat_major.trace import TraceError, trace_feature
from etat_major.trail import TrailError, load_wiring
from etat_major.workspace import Workspace, WorkspaceError, load_workspace

OK, PROBLEMS, USAGE = 0, 1, 2
_ISSUE_PATH_LIMIT = 256
_INVALID_LINE_LIMIT = 512


EXIT_CODES = (
    "Exit codes\n"
    "0 success, including warnings and unsourced findings\n"
    "1 missing, stale or gap trace items, or workspace validation issues\n"
    "2 usage errors, including unknown features and invalid workspaces or graphs"
)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        detail = message if len(message) <= 80 else message[:80] + "…"
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
    decisions = sub.add_parser("decisions", help="decision records")
    dsub = decisions.add_subparsers(dest="action", required=True)
    dlist = dsub.add_parser(
        "list", help="list all decisions, rejected and postponed included", **help_options
    )
    dlist.add_argument("--workspace", type=Path, required=True)
    return parser


def _err(message: str) -> None:
    print(f"error: {safe(message)}", file=sys.stderr)


def _open_workspace(path: Path) -> Workspace | None:
    try:
        ws = load_workspace(path)
    except WorkspaceError as exc:
        _err(str(exc))
        return None
    for issue in ws.issues:
        issue = replace(issue, path=safe(issue.path, limit=_ISSUE_PATH_LIMIT))
        print(safe(f"invalid: {issue}", limit=_INVALID_LINE_LIMIT), file=sys.stderr)
    if ws.omitted_issues:
        print(f"... {ws.omitted_issues} more issues", file=sys.stderr)
    return ws


def _trace(args: argparse.Namespace) -> int:
    try:
        ref = parse_ref(args.ref)
    except RefError as exc:
        _err(str(exc))
        return USAGE
    if ref.kind != "feature":
        _err(f"expected a feature reference, got {bounded_repr(str(ref))}")
        return USAGE
    try:
        graph = load_graph(args.graph) if args.graph is not None else None
        trail = load_wiring(args.trail) if args.trail is not None else None
    except (FloorplanError, TrailError) as exc:
        _err(str(exc))
        return USAGE
    ws = _open_workspace(args.workspace)
    if ws is None:
        return USAGE
    try:
        trace = trace_feature(ws, graph, ref, trail=trail)
    except TraceError as exc:
        _err(str(exc))
        return USAGE
    sys.stdout.write(render_trace(trace))
    return PROBLEMS if trace.has_problems or ws.issues else OK


def _decisions_list(args: argparse.Namespace) -> int:
    ws = _open_workspace(args.workspace)
    if ws is None:
        return USAGE
    for warning in ws.warnings:
        print(f"warning: {safe(warning)}", file=sys.stderr)
    for d in sorted(ws.decisions, key=lambda d: d.id):
        by = d.decided_by or "none"
        print(safe(f"decision:{d.id}  {d.status}  {by}  {d.question}"))
    return PROBLEMS if ws.issues else OK


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return _trace(args) if args.command == "trace" else _decisions_list(args)


if __name__ == "__main__":
    sys.exit(main())
