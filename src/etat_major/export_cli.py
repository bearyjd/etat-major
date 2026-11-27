"""Export a read-only view as JSON without the optional web stack."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from etat_major.discover_view import discover_payload
from etat_major.planning_view import (
    PlanningInputs,
    inputs_from_args,
    inputs_parser,
    load_planning_view,
    planning_payload,
)
from etat_major.taskfile import TaskFileError
from etat_major.understand_export import understand_document


def export_parser(parser: ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True)
    for name, help_text in (
        ("planning", "print the Planning payload served at /project.json"),
        ("discover", "print the Discover research and decisions payload"),
    ):
        target = actions.add_parser(name, help=help_text)
        inputs_parser(target)
        _json_flag(target)
    _understand_parser(actions.add_parser("understand", help="print the Understand payload"))


def _json_flag(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", required=True, help="print JSON (the only supported format)"
    )


def _understand_parser(parser: ArgumentParser) -> None:
    """Only the inputs the contract lists: no evidence flags and no repository."""
    _json_flag(parser)
    parser.add_argument("--workspace", type=Path, required=True, help="intent workspace directory")
    parser.add_argument("--project", required=True, help="project identifier in the workspace")
    for flag, description in (
        ("components", "component YAML (defaults to workspace/components/PROJECT.yaml)"),
        ("graph", "recorded Floorplan graph"),
        ("trail", "recorded Trail wiring"),
    ):
        parser.add_argument(f"--{flag}", type=Path, help=description)
    for artifact in ("source", "floorplan", "trail"):
        parser.add_argument(
            f"--{artifact}-revision", help=f"trusted {artifact} snapshot commit SHA"
        )
    parser.add_argument("--include-files", action="store_true", help="list recorded file paths")


def _run_understand(args: Namespace) -> int:
    inputs = PlanningInputs(
        args.workspace,
        args.project,
        components=args.components,
        graph=args.graph,
        trail=args.trail,
        source_revision=args.source_revision,
        floorplan_revision=args.floorplan_revision,
        trail_revision=args.trail_revision,
    )
    try:
        document = understand_document(inputs, include_files=args.include_files)
    except TaskFileError as exc:
        message = exc.message if exc.path == Path("serve") else f"{exc.filename}: {exc.message}"
        raise TaskFileError(Path("export understand"), exc.field_name, message) from None
    sys.stdout.write(document)
    return 0


def run_export(args: Namespace) -> int:
    if args.action == "understand":
        return _run_understand(args)
    try:
        view = load_planning_view(inputs_from_args(args))
    except TaskFileError as exc:
        if exc.path != Path("serve"):
            raise
        raise TaskFileError(Path(f"export {args.action}"), exc.field, exc.message) from None
    payload = (
        discover_payload(view._discover) if args.action == "discover" else planning_payload(view)
    )
    sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return 0
