"""CLI entry points for the recorded Gradle comparison."""

import argparse
from dataclasses import asdict, replace

from etat_major.cli_json import json_result
from etat_major.floorplan import load_graph
from etat_major.gradle import load_dependencies
from etat_major.gradle_drift import compare_dependencies
from etat_major.text_safety import public_text, safe
from etat_major.trail import load_wiring
from etat_major.workspace import Issue


def _safe_data(value: object) -> object:
    if isinstance(value, str):
        return safe(value)
    if isinstance(value, dict):
        return {key: _safe_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_data(item) for item in value]
    return value


def run_gradle(args: argparse.Namespace) -> int:
    dependencies = load_dependencies(args.root)
    issues = dependencies.issues
    if args.action == "deps":
        data = {
            "modules": [asdict(module) for module in dependencies.modules],
            "edges": [asdict(edge) for edge in dependencies.edges],
            "implicit_edges": [asdict(edge) for edge in dependencies.implicit_edges],
        }
    else:
        graph = load_graph(args.graph, architecture=True)
        trail = load_wiring(args.trail) if args.trail else None
        report = compare_dependencies(dependencies, graph, trail)
        data = asdict(report)
        if report.has_differences:
            issues += (
                Issue(
                    "gradle-drift",
                    "drift",
                    "candidate dependency or module differences",
                    severity="warning",
                ),
            )
    status = int(any(issue.blocking for issue in issues))
    data = {field: _safe_data(value) for field, value in data.items()}
    if args.format == "json":
        escaped = tuple(
            replace(i, path=safe(i.path), field=safe(i.field or "file"), message=safe(i.message))
            for i in issues
        )
        return json_result(f"gradle-{args.action}", status, data, issues=escaped)
    _render(data, verbose=getattr(args, "verbose", False))
    for issue in issues:
        print(safe(public_text(str(issue))))
    return status


def _render(data: dict, *, verbose: bool) -> None:
    summary = data.get("summary")
    if summary:
        print(f"{'Tier':<28} {'Count':>5}")
        for tier, count in summary.items():
            print(f"{tier:<28} {count:>5}")
        print()
    for field, rows in data.items():
        if field == "summary" or (summary and not rows) or (field == "call_only" and not verbose):
            continue
        print(field.replace("_", " ") + ":")
        for row in rows:
            if isinstance(row, str):
                print(safe(row))
            elif "directory" in row:
                print(safe(f"{row['id']}  {row['directory'] or '.'}"))
            elif "configuration" in row:
                _print_declaration(row)
            else:
                _print_comparison(row, verbose=verbose)


def _print_comparison(row: dict, *, verbose: bool) -> None:
    print(f"{row['source']} -> {row['target']}  evidence={row['evidence_count']}  {row['tier']}")
    if verbose:
        print(f"  Rank {row['rank']}")
        for reason in row["reasons"]:
            print(f"  {reason}")
    for declaration in row["declarations"]:
        _print_declaration(declaration, indent="  ")
    for item in row["evidence"]:
        confidence = f"/{item['confidence']}" if item["confidence"] else ""
        print(
            f"  {item['layer']} {item['relation']} "
            f"{item['provenance']}{confidence}  count={item['count']}"
        )


def _print_declaration(edge: dict, *, indent: str = "") -> None:
    test = "  test-only" if edge["test_only"] else ""
    via = f"  via {edge['plugin_id']} ({edge['plugin_class']})" if edge.get("implicit") else ""
    print(
        safe(
            f"{indent}{edge['source']} -> {edge['target']}  {edge['configuration']}{test}"
            f"  {edge['file']}:{edge['line']}{via}"
        )
    )
