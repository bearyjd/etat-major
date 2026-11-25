"""Export a read-only view as JSON without the optional web stack."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace

from etat_major.planning_view import (
    inputs_from_args,
    inputs_parser,
    load_planning_view,
    planning_payload,
)


def export_parser(parser: ArgumentParser) -> None:
    target = parser.add_subparsers(dest="action", required=True).add_parser(
        "planning", help="print the Planning payload served at /project.json"
    )
    inputs_parser(target)
    target.add_argument("--json", action="store_true", required=True, help="print JSON")


def run_export(args: Namespace) -> int:
    payload = planning_payload(load_planning_view(inputs_from_args(args)))
    sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return 0
